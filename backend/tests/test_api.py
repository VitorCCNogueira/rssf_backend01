import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import app
from config import DEFAULT_GATEWAY_ID, STATUS_OFFLINE_MINUTES
from identity import canonical_gateway_id, gateway_query_values
from models.medicao import MedicaoModel


class TestIdentityMapping(unittest.TestCase):
    def test_legacy_e_associado_pelo_par_gateway_no(self):
        self.assertEqual(canonical_gateway_id(1, 'gateway_legacy'), 'gateway_node_1')
        self.assertEqual(canonical_gateway_id(44204, 'gateway_legacy'), 'gateway_node_2')
        self.assertEqual(canonical_gateway_id(999, 'gateway_legacy'), 'gateway_legacy')

    def test_consulta_canonica_alcanca_somente_o_legacy_do_mesmo_no(self):
        self.assertEqual(
            gateway_query_values(1, 'gateway_node_1'),
            ('gateway_node_1', 'gateway_legacy')
        )
        self.assertEqual(
            gateway_query_values(44204, 'gateway_node_2'),
            ('gateway_node_2', 'gateway_legacy')
        )
        self.assertEqual(gateway_query_values(999, 'gateway_unknown'), ('gateway_unknown',))

    def test_no_de_laboratorio_normaliza_gateway_antigo_desconhecido(self):
        with patch.multiple('config', LAB_SENSOR_ID='21768', LAB_GATEWAY_ID='gateway_lab_01'):
            self.assertEqual(canonical_gateway_id(21768, 'gateway_unknown'), 'gateway_lab_01')
            self.assertIn('gateway_unknown', gateway_query_values(21768, 'gateway_lab_01'))


class TestSalvarDados(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_no_de_laboratorio_sem_gateway_envia_status_e_descarta_temperaturas(self, mock_salvar):
        with patch.multiple('config', LAB_SENSOR_ID='21768', LAB_GATEWAY_ID='gateway_lab_01'):
            response = self.client.post('/api/salvar_dados', json={
                'senderAddress': 21768,
                'temp_ds1': -2.09847e-38,
                'temp_ds3': 2.09847e-38,
                'rssi': -120,
            })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['gateway_id'], 'gateway_lab_01')
        saved_data = mock_salvar.call_args.args[0]
        self.assertIsNone(saved_data['temp_ds1'])
        self.assertIsNone(saved_data['temp_ds3'])
        self.assertEqual(mock_salvar.call_args.args[1], 'gateway_lab_01')

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_nos_conhecidos_sem_gateway_recebem_identidades_estaveis_distintas(self, mock_salvar):
        for sensor_id, gateway_id in ((1, 'gateway_node_1'), (44204, 'gateway_node_2')):
            with self.subTest(sensor_id=sensor_id):
                response = self.client.post('/api/salvar_dados', json={'senderAddress': sensor_id})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.get_json()['gateway_id'], gateway_id)
                self.assertEqual(mock_salvar.call_args.args[1], gateway_id)

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_gateway_explicito_aceita_sensor_uint16_e_rssi_nulo(self, mock_salvar):
        payload = {
            'gateway_id': 'gateway_remote_02',
            'senderAddress': 44204,
            'rssi': None,
            'temp_ds1': 28.4,
            'temp_ds2': 28.8,
            'temp_ds3': 29.1,
            'temp_ds4': 29.6,
            'temp_ds5': 30.1,
            'temp_ds6': 30.5,
        }

        response = self.client.post('/api/salvar_dados', json=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['sensor_id'], 44204)
        self.assertEqual(mock_salvar.call_args.args[0]['senderAddress'], 44204)
        self.assertEqual(mock_salvar.call_args.args[0]['rssi'], None)
        self.assertEqual(mock_salvar.call_args.args[1], 'gateway_remote_02')

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_limites_uint16_validos(self, mock_salvar):
        for sensor_id in (1, 65534):
            with self.subTest(sensor_id=sensor_id):
                response = self.client.post('/api/salvar_dados', json={'senderAddress': sensor_id})
                self.assertEqual(response.status_code, 201)

        self.assertEqual(mock_salvar.call_count, 2)

    def test_limites_uint16_reservados_ou_invalidos_sao_rejeitados(self):
        for sensor_id in (0, 65535, 65536, 70000, -1, '44204', True):
            with self.subTest(sensor_id=sensor_id):
                response = self.client.post('/api/salvar_dados', json={'senderAddress': sensor_id})
                self.assertEqual(response.status_code, 400)

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_no_desconhecido_sem_gateway_usa_fallback_e_rssi_numerico(self, mock_salvar):
        response = self.client.post('/api/salvar_dados', json={
            'senderAddress': 12345,
            'rssi': -87.5,
            'temp_ds1': 28.4,
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['gateway_id'], DEFAULT_GATEWAY_ID)
        self.assertEqual(mock_salvar.call_args.args[1], DEFAULT_GATEWAY_ID)
        self.assertEqual(mock_salvar.call_args.args[0]['rssi'], -87.5)

    @patch('models.medicao.MedicaoModel.salvar', return_value=True)
    def test_rssi_ausente_e_aceito_como_nulo(self, mock_salvar):
        response = self.client.post('/api/salvar_dados', json={
            'gateway_id': 'gateway_remote_02',
            'senderAddress': 44204,
        })

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(mock_salvar.call_args.args[0].get('rssi'))

    def test_gateway_rssi_e_temperatura_invalidos_sao_rejeitados(self):
        invalid_payloads = (
            {'gateway_id': '', 'senderAddress': 44204},
            {'gateway_id': 'inv@lido!', 'senderAddress': 44204},
            {'senderAddress': 44204, 'rssi': '-87.5'},
            {'senderAddress': 44204, 'temp_ds1': '28.4'},
            {'senderAddress': 44204, 'temp_ds1': float('nan')},
            {'senderAddress': 44204, 'rssi': float('inf')},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/salvar_dados', json=payload).status_code, 400)


class TestLeiturasGet(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('models.medicao.MedicaoModel.get_por_periodo', return_value=[])
    def test_periodo_repassa_filtros_sensor_gateway_e_datas(self, mock_periodo):
        response = self.client.get(
            '/api/medicoes?inicio=2026-07-10T10:00:00&fim=2026-07-10T11:00:00'
            '&sensor_id=44204&gateway_id=gateway_node_2'
        )

        self.assertEqual(response.status_code, 200)
        mock_periodo.assert_called_once_with(
            datetime(2026, 7, 10, 10), datetime(2026, 7, 10, 11), '44204', 'gateway_node_2'
        )

    @patch('models.medicao.MedicaoModel.get_recentes')
    def test_recentes_retorna_colecao_global_e_filtro_por_sensor(self, mock_recentes):
        mock_recentes.return_value = [
            {'sensor_id': 1, 'gateway_id': 'gateway_node_1'},
            {'sensor_id': 44204, 'gateway_id': 'gateway_node_2'},
        ]
        response = self.client.get('/api/medicoes/recentes')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 2)
        mock_recentes.assert_called_once_with(None, None)

        mock_recentes.reset_mock()
        mock_recentes.return_value = [{'sensor_id': 44204, 'gateway_id': 'gateway_node_2'}]
        response = self.client.get('/api/medicoes/recentes?sensor_id=44204&gateway_id=gateway_node_2')
        self.assertEqual(response.status_code, 200)
        mock_recentes.assert_called_once_with('44204', 'gateway_node_2')

    @patch('models.medicao.MedicaoModel.get_recentes')
    def test_status_retorna_um_item_por_gateway_e_sensor(self, mock_recentes):
        mock_recentes.return_value = [
            {'sensor_id': 1, 'gateway_id': 'gateway_node_1', 'data_hora': datetime.now().isoformat()},
            {'sensor_id': 44204, 'gateway_id': 'gateway_node_2', 'data_hora': (datetime.now() - timedelta(minutes=STATUS_OFFLINE_MINUTES + 1)).isoformat()},
        ]

        response = self.client.get('/api/status')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual({item['sensor_id'] for item in payload}, {1, 44204})
        self.assertEqual(set(payload[0]), {'sensor_id', 'gateway_id', 'ultima_transmissao', 'status', 'minutos_desde_ultima', 'server_time', 'profile'})


class TestPersistenceAndSchema(unittest.TestCase):
    @patch('models.medicao.mysql.connector.connect')
    def test_salvar_faz_rollback_em_erro_de_insert(self, mock_connect):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError('database failure')
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        mock_connect.return_value = connection

        with self.assertRaisesRegex(RuntimeError, 'database failure'):
            MedicaoModel.salvar({'senderAddress': 44204}, 'gateway_node_2')

        connection.rollback.assert_called_once()
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    @patch('models.medicao.mysql.connector.connect')
    def test_consultas_usam_data_hora_e_filtros_parametrizados(self, mock_connect):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        mock_connect.return_value = connection

        MedicaoModel.get_por_periodo('2026-07-10T10:00:00', '2026-07-10T11:00:00', 44204, 'gateway_node_2')
        sql, params = cursor.execute.call_args.args
        self.assertIn('data_hora BETWEEN %s AND %s', sql)
        self.assertIn('sensor_id = %s', sql)
        self.assertIn('gateway_id IN (%s, %s)', sql)
        self.assertEqual(params, ('2026-07-10T10:00:00', '2026-07-10T11:00:00', 44204, 'gateway_node_2', 'gateway_legacy'))

        cursor.reset_mock()
        MedicaoModel.get_recentes(44204, 'gateway_node_2')
        sql, params = cursor.execute.call_args.args
        self.assertIn('MAX(data_hora)', sql)
        self.assertIn('GROUP BY sensor_id, gateway_id', sql)
        self.assertIn('MAX(m3.id)', sql)
        self.assertIn('m3.gateway_id = m1.gateway_id', sql)
        self.assertEqual(params, (44204, 'gateway_node_2', 'gateway_legacy'))

        cursor.reset_mock()
        MedicaoModel.get_por_sensor(1, 3, 'gateway_node_1')
        sql, params = cursor.execute.call_args.args
        self.assertIn('gateway_id IN (%s, %s)', sql)
        self.assertEqual(params, (1, 'gateway_node_1', 'gateway_legacy', 3))

    @patch('models.medicao.mysql.connector.connect')
    def test_recentes_agrupa_por_gateway_sensor_e_desempata_por_id(self, mock_connect):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        mock_connect.return_value = connection

        MedicaoModel.get_recentes()

        sql, params = cursor.execute.call_args.args
        self.assertIn('GROUP BY sensor_id, gateway_id', sql)
        self.assertIn('ultimas.gateway_id = m1.gateway_id', sql)
        self.assertIn('ultimas.sensor_id = m1.sensor_id', sql)
        self.assertIn('ultimas.ultima_data_hora = m1.data_hora', sql)
        self.assertIn('MAX(m3.id)', sql)
        self.assertEqual(params, ())

    @patch('models.medicao.mysql.connector.connect')
    def test_recentes_unifica_apenas_a_transicao_legacy_do_mesmo_no(self, mock_connect):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, '2026-07-10T10:00:00', 'gateway_legacy', 44204, 30, 30, 30, 30, 30, 30, None),
            (2, '2026-07-10T11:00:00', 'gateway_node_2', 44204, 31, 31, 31, 31, 31, 31, None),
        ]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        mock_connect.return_value = connection

        readings = MedicaoModel.get_recentes()

        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0]['gateway_id'], 'gateway_node_2')
        self.assertEqual(readings[0]['id'], 2)

    @patch('models.medicao.mysql.connector.connect')
    def test_agregados_excluem_85_apenas_do_no_1(self, mock_connect):
        cursor = MagicMock()
        cursor.fetchone.return_value = {}
        connection = MagicMock()
        connection.cursor.return_value = cursor
        connection.is_connected.return_value = True
        mock_connect.return_value = connection

        MedicaoModel.get_estatisticas_por_sensor(sensor_id=1, gateway_id='gateway_node_1')

        sql, params = cursor.execute.call_args.args
        self.assertIn('NOT (sensor_id = 1 AND temp_ds1 = 85)', sql)
        self.assertIn('gateway_id IN (%s, %s)', sql)
        self.assertEqual(params, (1, 'gateway_node_1', 'gateway_legacy'))

    def test_schema_e_migracao_aceitam_uint16(self):
        backend_dir = Path(__file__).resolve().parents[1]
        schema = (backend_dir / 'database' / 'schema.sql').read_text(encoding='utf-8')
        migration = (backend_dir / 'database' / 'migrations' / '002_expand_sensor_id_to_uint16.sql').read_text(encoding='utf-8')

        self.assertIn('sensor_id SMALLINT UNSIGNED NOT NULL', schema)
        self.assertIn('MODIFY COLUMN sensor_id SMALLINT UNSIGNED NOT NULL', migration)

    def test_schema_e_migracao_tem_indice_para_descoberta_recente(self):
        backend_dir = Path(__file__).resolve().parents[1]
        schema = (backend_dir / 'database' / 'schema.sql').read_text(encoding='utf-8')
        migration = (backend_dir / 'database' / 'migrations' / '004_optimize_recent_collection_points.sql').read_text(encoding='utf-8')
        expected_columns = '(sensor_id, gateway_id, data_hora, id)'

        self.assertIn('idx_medicoes_latest_point', schema)
        self.assertIn(expected_columns, schema)
        self.assertIn('idx_medicoes_latest_point', migration)
        self.assertIn(expected_columns, migration)
        self.assertIn('information_schema.statistics', migration)

    def test_prefixos_de_migracao_sao_unicos(self):
        migrations_dir = Path(__file__).resolve().parents[1] / 'database' / 'migrations'
        prefixes = [path.name.split('_', 1)[0] for path in migrations_dir.glob('*.sql')]
        self.assertEqual(len(prefixes), len(set(prefixes)))


if __name__ == '__main__':
    unittest.main()

