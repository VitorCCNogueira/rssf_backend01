import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import app
from monitoring import status_for, iso_utc, point_profile
from models.medicao import MedicaoModel
from test_batches import payload


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.now = datetime(2026, 10, 19, 15, tzinfo=timezone.utc)

    def test_legacy_thresholds_and_lab_isolation(self):
        with patch.multiple('config', LAB_SENSOR_ID='44204', LAB_GATEWAY_ID='gateway_lab_01'):
            for gateway, boundaries in [('gateway_node_2', (60, 180)), ('gateway_lab_01', (540, 1440))]:
                online, offline = boundaries
                for age, expected in [(0, 'online'), (online - 1, 'online'), (online, 'instavel'), (offline, 'offline')]:
                    row = {'sensor_id': 44204, 'gateway_id': gateway, 'data_hora': self.now - timedelta(minutes=age)}
                    self.assertEqual(status_for(row, self.now)['status'], expected)
            self.assertEqual(point_profile(1, 'gateway_lab_01')['mode'], 'legacy')

    def test_lab_sensor_id_survives_receiver_unknown_gateway_fallback(self):
        with patch.multiple('config', LAB_SENSOR_ID='21768', LAB_GATEWAY_ID='gateway_lab_01'):
            row = {'sensor_id': 21768, 'gateway_id': 'gateway_unknown', 'data_hora': self.now}
            self.assertEqual(point_profile(21768, 'gateway_unknown')['mode'], 'laboratory')
            self.assertEqual(status_for(row, self.now)['profile']['expected_interval_minutes'], 480)

    def test_timezone_offsets_are_equivalent_and_future_is_unknown(self):
        self.assertEqual(iso_utc('2026-10-19T12:00:00-03:00'), '2026-10-19T15:00:00Z')
        row = {'sensor_id': 1, 'gateway_id': 'gateway_node_1', 'data_hora': '2026-10-19T12:00:00-03:00'}
        self.assertEqual(status_for(row, self.now)['status'], 'online')
        row['data_hora'] = self.now + timedelta(hours=3)
        self.assertEqual(status_for(row, self.now)['status'], 'unknown')

    @patch('models.medicao.MedicaoModel.get_recentes')
    def test_dashboard_reuses_one_query_and_never_caches_status(self, recent):
        recent.return_value = [{'sensor_id': 1, 'gateway_id': 'gateway_node_1', 'data_hora': '2020-01-01T00:00:00Z'}]
        response = self.client.get('/api/dashboard')
        recent.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['statuses'][0]['status'], 'offline')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    @patch('models.medicao.MedicaoModel.get_estatisticas_por_sensor', return_value=[])
    def test_statistics_without_dates_are_scoped_to_whole_point(self, stats):
        self.assertEqual(self.client.get('/api/medicoes/estatisticas?sensor_id=1&gateway_id=gateway_node_1').status_code, 200)
        stats.assert_called_once_with(None, None, '1', 'gateway_node_1')

    @patch('models.medicao.MedicaoModel.get_estatisticas_por_sensor', return_value=[])
    def test_dates_validate_before_database_and_convert_offset(self, stats):
        for query in ['inicio=bad&fim=bad', 'inicio=2026-10-19', 'inicio=2026-10-20&fim=2026-10-19']:
            self.assertEqual(self.client.get('/api/medicoes/estatisticas?' + query).status_code, 400)
        stats.assert_not_called()
        self.client.get('/api/medicoes/estatisticas', query_string={'inicio': '2026-10-19T12:00:00-03:00', 'fim': '2026-10-19T13:00:00-03:00'})
        self.assertEqual(stats.call_args.args[:2], (datetime(2026, 10, 19, 15), datetime(2026, 10, 19, 16)))

    @patch('models.medicao.mysql.connector.connect')
    def test_unconfigured_batch_and_wrong_gateway_never_write(self, connect):
        with patch('config.LAB_SENSOR_ID', ''):
            self.assertEqual(self.client.post('/api/salvar_dados', json=payload()).status_code, 400)
        with patch.multiple('config', LAB_SENSOR_ID='44204', LAB_GATEWAY_ID='other_gateway'):
            self.assertEqual(self.client.post('/api/salvar_dados', json=payload()).status_code, 400)
        connect.assert_not_called()

    @patch('models.medicao.mysql.connector.connect')
    def test_batch_without_current_sample_rejected(self, connect):
        with patch.multiple('config', LAB_SENSOR_ID='44204', LAB_GATEWAY_ID='gateway_lab_01'):
            data = payload()
            data['medicoes'] = data['medicoes'][:-1]
            self.assertEqual(self.client.post('/api/salvar_dados', json=data).status_code, 400)
        connect.assert_not_called()

    @patch('models.medicao.mysql.connector.connect')
    def test_bounded_history_keeps_gateway_scope_and_utc(self, connect):
        cursor = connect.return_value.cursor.return_value
        cursor.fetchone.return_value = {'first_ts': 0, 'last_ts': 10000000, 'total': 10001}
        cursor.fetchall.return_value = [{'id': 5, 'data_hora': datetime(2026, 10, 19), 'rssi': -80,
                                         'sample_count': 20, **{f'temp_ds{i}': 25.0 for i in range(1, 7)}}]
        result = MedicaoModel.get_history_summary(1, 'gateway_node_1')
        self.assertTrue(result['aggregated'])
        self.assertGreater(result['bucket_seconds'], 10000)
        self.assertTrue(result['readings'][0]['data_hora'].endswith('Z'))
        self.assertEqual(cursor.execute.call_args.args[1][:3], (1, 'gateway_node_1', 'gateway_legacy'))

