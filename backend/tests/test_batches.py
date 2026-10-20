import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app import app
from config import LAB_ONLINE_MINUTES as STATUS_ONLINE_MINUTES, LAB_OFFLINE_MINUTES as STATUS_OFFLINE_MINUTES


def payload():
    return {
        'senderAddress': 44204,
        'rssi': -80,
        'gateway_id': 'gateway_lab_01',
        'medicoes': [
            {'idade_min': (15 - j) * 30,
             **{f'temp_ds{i}': 25 + j / 10 + i for i in range(1, 7)}}
            for j in range(16)
        ],
    }


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.lab_config = patch.multiple('config', LAB_SENSOR_ID='44204', LAB_GATEWAY_ID='gateway_lab_01')
        self.lab_config.start()
        self.addCleanup(self.lab_config.stop)
        self.client = app.test_client()
        self.received = datetime(2026, 10, 14, 3, 15)
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.fetchone.return_value = (self.received,)
        self.connect_patch = patch('models.medicao.mysql.connector.connect', return_value=self.connection)
        self.connect = self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)

    def test_full_batch_persists_each_reading_with_its_time_in_one_transaction(self):
        data = payload()
        response = self.client.post('/api/salvar_dados', json=data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['medicoes_salvas'], 16)
        self.cursor.execute.assert_called_once_with('SELECT CURRENT_TIMESTAMP')
        sql, rows = self.cursor.executemany.call_args.args
        self.assertIn('data_hora', sql)
        self.assertEqual(len(rows), 16)
        for row, reading in zip(rows, data['medicoes']):
            self.assertEqual(row, (
                self.received - timedelta(minutes=reading['idade_min']),
                'gateway_lab_01', 44204,
                *(None for _ in range(6)), -80,
            ))
        self.assertEqual(rows[0][0].day, 13)  # atravessa a meia-noite
        self.assertEqual(rows[-1][0], self.received)
        self.connection.commit.assert_called_once()
        self.connection.rollback.assert_not_called()
        self.cursor.close.assert_called_once()
        self.connection.close.assert_called_once()

    def test_single_reading_explicit_gateway_nullable_temperature_and_optional_rssi(self):
        data = payload()
        data['gateway_id'] = 'gateway_lab_01'
        data.pop('rssi')
        data['medicoes'] = [data['medicoes'][-1]]
        data['medicoes'][0]['temp_ds1'] = None
        response = self.client.post('/api/salvar_dados', json=data)
        self.assertEqual(response.status_code, 201)
        row = self.cursor.executemany.call_args.args[1][0]
        self.assertEqual(row[:4], (self.received, 'gateway_lab_01', 44204, None))
        self.assertIsNone(row[-1])

    def test_invalid_batch_is_rejected_before_connecting(self):
        cases = []
        for readings in (None, {}, [], [payload()['medicoes'][0]] * 17, [None], [1]):
            data = payload()
            data['medicoes'] = readings
            cases.append(data)
        for age in (-1, 451, True, 1.5, '30', None, 450):
            data = payload()
            data['medicoes'][-1]['idade_min'] = age
            cases.append(data)
        for temp in (True, '25', float('nan'), float('inf'), {}):
            data = payload()
            data['medicoes'][-1]['temp_ds6'] = temp
            cases.append(data)
        for key in ('temp_ds6', 'idade_min'):
            data = payload()
            del data['medicoes'][-1][key]
            cases.append(data)
        data = payload()
        data['temp_ds1'] = 25
        cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.client.post('/api/salvar_dados', json=data).status_code, 400)
        self.connect.assert_not_called()

    def test_insert_failure_rolls_back_entire_batch(self):
        self.cursor.executemany.side_effect = RuntimeError('insert failed')
        response = self.client.post('/api/salvar_dados', json=payload())
        self.assertEqual(response.status_code, 500)
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once()
        self.cursor.close.assert_called_once()
        self.connection.close.assert_called_once()

    def test_legacy_payload_still_uses_one_insert(self):
        response = self.client.post('/api/salvar_dados', json={
            'senderAddress': 44204, 'temp_ds1': 26, 'rssi': -80,
        })
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('medicoes_salvas', response.json)
        self.cursor.executemany.assert_not_called()
        self.assertEqual(self.cursor.execute.call_args.args[1], (
            'gateway_node_2', 44204, 26, None, None, None, None, None, -80,
        ))

    @patch('routes.medicoes.datetime')
    @patch('models.medicao.MedicaoModel.get_recentes')
    def test_status_respects_batch_interval_and_configured_boundaries(self, recent, clock):
        clock.now.return_value = self.received
        for minutes, expected in (
            (480, 'online'),
            (STATUS_ONLINE_MINUTES - 1, 'online'),
            (STATUS_ONLINE_MINUTES, 'instavel'),
            (STATUS_OFFLINE_MINUTES - 1, 'instavel'),
            (STATUS_OFFLINE_MINUTES, 'offline'),
        ):
            with self.subTest(minutes=minutes):
                recent.return_value = [{
                    'sensor_id': 44204, 'gateway_id': 'gateway_lab_01',
                    'data_hora': self.received - timedelta(minutes=minutes),
                }]
                response = self.client.get('/api/status')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json[0]['status'], expected)


if __name__ == '__main__':
    unittest.main()
