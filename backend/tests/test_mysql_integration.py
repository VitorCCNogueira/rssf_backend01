"""Run only against a disposable *_test database with explicit opt-in."""
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import mysql.connector
from app import app
from config import DB_CONFIG
from models.medicao import MedicaoModel


@unittest.skipUnless(os.getenv('RUN_MYSQL_INTEGRATION') == '1', 'Disposable MySQL not configured')
class MySQLIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DB_CONFIG.get('database') or '').endswith('_test'):
            raise RuntimeError('Integration tests require a disposable *_test database')
        cls.conn = mysql.connector.connect(**DB_CONFIG)
        cls.cursor = cls.conn.cursor()
        schema = (Path(__file__).parents[1] / 'database/schema.sql').read_text(encoding='utf-8')
        cls.cursor.execute(schema[schema.index('CREATE TABLE'):])
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.cursor.close()
        cls.conn.close()

    def setUp(self):
        self.cursor.execute('DELETE FROM medicoes')
        self.conn.commit()
        self.client = app.test_client()

    def test_legacy_and_lab_coexist_with_utc_and_null_temperatures(self):
        with patch('config.LAB_SENSOR_ID', '12345'), patch('config.LAB_GATEWAY_ID', 'gateway_lab_01'):
            legacy = self.client.post('/api/salvar_dados', json={'senderAddress': 1, 'temp_ds1': 25})
            self.assertEqual(legacy.status_code, 201)
            batch = {'senderAddress': 12345, 'gateway_id': 'gateway_lab_01', 'rssi': -80,
                     'medicoes': [dict(idade_min=age, **{f'temp_ds{i}': -55 for i in range(1, 7)})
                                  for age in (30, 0)]}
            self.assertEqual(self.client.post('/api/salvar_dados', json=batch).status_code, 201)
            snapshot = self.client.get('/api/dashboard').get_json()
            self.assertEqual(len(snapshot['readings']), 2)
            lab = next(row for row in snapshot['readings'] if row['sensor_id'] == 12345)
            self.assertIsNone(lab['temp_ds1'])
            self.assertTrue(lab['data_hora'].endswith('Z'))
            self.assertEqual(lab['profile']['mode'], 'laboratory')
            self.assertEqual({row['status'] for row in snapshot['statuses']}, {'online'})
            history = MedicaoModel.get_history_summary('12345', 'gateway_lab_01')
            self.assertEqual(history['total'], 2)
            times = [datetime.fromisoformat(row['data_hora'].replace('Z', '+00:00')) for row in history['readings']]
            self.assertEqual(times[1] - times[0], timedelta(minutes=30))
            stats = MedicaoModel.get_estatisticas_por_sensor(sensor_id='1', gateway_id='gateway_node_1')
            self.assertEqual(stats[0]['avg'], 25)
            self.assertEqual(stats[0]['count'], 1)

    def test_large_history_is_bounded_scoped_and_stats_remain_exact(self):
        start = datetime(2026, 1, 1)
        rows = [(start + timedelta(minutes=i), 'gateway_node_1', 1, float(i % 50)) for i in range(2500)]
        rows.append((start, 'other_gateway', 1, 999))
        self.cursor.executemany('INSERT INTO medicoes (data_hora,gateway_id,sensor_id,temp_ds1) VALUES (%s,%s,%s,%s)', rows)
        self.conn.commit()
        history = MedicaoModel.get_history_summary('1', 'gateway_node_1')
        self.assertEqual(history['total'], 2500)
        self.assertLessEqual(len(history['readings']), 1000)
        self.assertEqual(sum(row['sample_count'] for row in history['readings']), 2500)
        self.assertTrue(history['aggregated'])
        stats = MedicaoModel.get_estatisticas_por_sensor(sensor_id='1', gateway_id='gateway_node_1')[0]
        self.assertEqual(stats['count'], 2500)
        self.assertEqual(stats['avg'], 24.5)
        self.assertEqual(stats['max'], 49)
        filtered = MedicaoModel.get_history_summary('1', 'gateway_node_1', start, start + timedelta(minutes=9))
        self.assertEqual(filtered['total'], 10)
