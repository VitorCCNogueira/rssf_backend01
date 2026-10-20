# models/medicao.py
from datetime import timedelta

import mysql.connector
from config import DB_CONFIG
from identity import canonical_gateway_id, gateway_query_values
from monitoring import iso_utc, point_profile

class MedicaoModel:
    SENSOR_COLUMNS = ('ds1', 'ds2', 'ds3', 'ds4', 'ds5', 'ds6')

    @staticmethod
    def salvar(data, gateway_id):
        # Ordem: gateway_id, id(sensor_id), s1, s2, s3, s4, s5, s6, rssi
        values = (
            gateway_id,
            data.get('senderAddress'),
            data.get('temp_ds1'), data.get('temp_ds2'),
            data.get('temp_ds3'), data.get('temp_ds4'),
            data.get('temp_ds5'), data.get('temp_ds6'),
            data.get('rssi')
        )

        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()

            sql = """INSERT INTO medicoes
                     (gateway_id, sensor_id, temp_ds1, temp_ds2, temp_ds3, temp_ds4, temp_ds5, temp_ds6, rssi)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""

            cursor.execute(sql, values)
            conn.commit()
            return True
        except Exception as e:
            if conn and conn.is_connected():
                conn.rollback()
            raise e
        finally:
            if conn and conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def salvar_lote(data, gateway_id):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            # Mesmo relogio/fuso de CURRENT_TIMESTAMP usado pelo INSERT legado.
            # Uma unica referencia evita deslocamentos entre as leituras do lote.
            cursor.execute('SELECT CURRENT_TIMESTAMP')
            received_at = cursor.fetchone()[0]
            values = [
                (received_at - timedelta(minutes=reading['idade_min']),
                 gateway_id, data['senderAddress'],
                 *(reading[f'temp_ds{i}'] for i in range(1, 7)), data.get('rssi'))
                for reading in data['medicoes']
            ]
            cursor.executemany(
                """INSERT INTO medicoes
                   (data_hora, gateway_id, sensor_id, temp_ds1, temp_ds2,
                    temp_ds3, temp_ds4, temp_ds5, temp_ds6, rssi)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                values,
            )
            conn.commit()
            return True
        except Exception:
            if conn and conn.is_connected():
                conn.rollback()
            raise
        finally:
            if conn and conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def _to_dict(row):
        created_at_str = iso_utc(row[1])
        profile = point_profile(row[3], canonical_gateway_id(row[3], row[2]))
        temperatures = (None, None, None, None, None, None) if not profile['has_sensors'] else row[4:10]

        return {
            "id": row[0],
            "data_hora": created_at_str,
            "gateway_id": canonical_gateway_id(row[3], row[2]),
            "sensor_id": row[3],
            "temp_ds1": temperatures[0],
            "temp_ds2": temperatures[1],
            "temp_ds3": temperatures[2],
            "temp_ds4": temperatures[3],
            "temp_ds5": temperatures[4],
            "temp_ds6": temperatures[5],
            "rssi": row[10],
            "profile": profile,
        }

    @staticmethod
    def get_por_sensor(sensor_id, limite=100, gateway_id=None):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()

            sql = "SELECT id, data_hora, gateway_id, sensor_id, temp_ds1, temp_ds2, temp_ds3, temp_ds4, temp_ds5, temp_ds6, rssi FROM medicoes WHERE sensor_id = %s"
            params = [sensor_id]

            gateway_values = gateway_query_values(sensor_id, gateway_id)
            if gateway_values:
                placeholders = ", ".join(["%s"] * len(gateway_values))
                sql += f" AND gateway_id IN ({placeholders})"
                params.extend(gateway_values)

            sql += " ORDER BY data_hora DESC LIMIT %s"
            params.append(int(limite))

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [MedicaoModel._to_dict(row) for row in rows]
        except Exception as e:
            raise e
        finally:
            if conn and conn.is_connected():
                if cursor: cursor.close()
                conn.close()

    @staticmethod
    def get_por_periodo(inicio, fim, sensor_id=None, gateway_id=None):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            sql = "SELECT id, data_hora, gateway_id, sensor_id, temp_ds1, temp_ds2, temp_ds3, temp_ds4, temp_ds5, temp_ds6, rssi FROM medicoes WHERE data_hora BETWEEN %s AND %s"
            params = [inicio, fim]

            if sensor_id:
                sql += " AND sensor_id = %s"
                params.append(sensor_id)
            gateway_values = gateway_query_values(sensor_id, gateway_id)
            if gateway_values:
                placeholders = ", ".join(["%s"] * len(gateway_values))
                sql += f" AND gateway_id IN ({placeholders})"
                params.extend(gateway_values)

            sql += " ORDER BY data_hora DESC"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [MedicaoModel._to_dict(row) for row in rows]
        except Exception as e:
            raise e
        finally:
            if conn and conn.is_connected():
                if cursor: cursor.close()
                conn.close()

    @staticmethod
    def get_recentes(sensor_id=None, gateway_id=None):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()

            sql = """
                SELECT m1.id, m1.data_hora, m1.gateway_id, m1.sensor_id,
                       m1.temp_ds1, m1.temp_ds2, m1.temp_ds3,
                       m1.temp_ds4, m1.temp_ds5, m1.temp_ds6, m1.rssi
                FROM medicoes m1
                INNER JOIN (
                    SELECT gateway_id, sensor_id, MAX(data_hora) AS ultima_data_hora
                    FROM medicoes
                    WHERE 1 = 1
            """
            params = []
            if sensor_id:
                sql += " AND sensor_id = %s"
                params.append(sensor_id)
            gateway_values = gateway_query_values(sensor_id, gateway_id)
            if gateway_values:
                placeholders = ", ".join(["%s"] * len(gateway_values))
                sql += f" AND gateway_id IN ({placeholders})"
                params.extend(gateway_values)

            sql += """
                    GROUP BY sensor_id, gateway_id
                ) AS ultimas
                  ON ultimas.gateway_id = m1.gateway_id
                 AND ultimas.sensor_id = m1.sensor_id
                 AND ultimas.ultima_data_hora = m1.data_hora
                WHERE m1.id = (
                    SELECT MAX(m3.id)
                    FROM medicoes m3
                    WHERE m3.gateway_id = m1.gateway_id
                      AND m3.sensor_id = m1.sensor_id
                      AND m3.data_hora = m1.data_hora
                )
                ORDER BY m1.sensor_id, m1.gateway_id
            """

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            latest_by_point = {}
            for row in rows:
                item = MedicaoModel._to_dict(row)
                key = (item['gateway_id'], str(item['sensor_id']))
                current = latest_by_point.get(key)
                if current is None or (item['data_hora'], item['id']) > (current['data_hora'], current['id']):
                    latest_by_point[key] = item
            return list(latest_by_point.values())
        except Exception as e:
            raise e
        finally:
            if conn and conn.is_connected():
                if cursor: cursor.close()
                conn.close()

    @staticmethod
    def get_estatisticas_por_sensor(inicio=None, fim=None, sensor_id=None, gateway_id=None):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor(dictionary=True)

            def valid_temp_expr(sensor):
                column = f"temp_{sensor}"
                return (
                    f"CASE WHEN {column} IS NOT NULL AND {column} <> -127 "
                    f"AND NOT (sensor_id = 1 AND {column} = 85) THEN {column} END"
                )

            aggregate_sql = ", ".join(
                [
                    f"AVG({valid_temp_expr(sensor)}) AS avg_{sensor}, "
                    f"MAX({valid_temp_expr(sensor)}) AS max_{sensor}, "
                    f"MIN({valid_temp_expr(sensor)}) AS min_{sensor}, "
                    f"COUNT({valid_temp_expr(sensor)}) AS count_{sensor}"
                    for sensor in MedicaoModel.SENSOR_COLUMNS
                ]
            )

            sql = f"SELECT {aggregate_sql} FROM medicoes"
            params = []

            conditions = []
            if inicio and fim:
                conditions.append("data_hora BETWEEN %s AND %s")
                params.extend([inicio, fim])
            if sensor_id:
                conditions.append("sensor_id = %s")
                params.append(sensor_id)
            gateway_values = gateway_query_values(sensor_id, gateway_id)
            if gateway_values:
                placeholders = ", ".join(["%s"] * len(gateway_values))
                conditions.append(f"gateway_id IN ({placeholders})")
                params.extend(gateway_values)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            cursor.execute(sql, tuple(params))
            row = cursor.fetchone() or {}

            return [
                {
                    "sensor_id": sensor,
                    "avg": row.get(f"avg_{sensor}"),
                    "max": row.get(f"max_{sensor}"),
                    "min": row.get(f"min_{sensor}"),
                    "count": row.get(f"count_{sensor}", 0)
                }
                for sensor in MedicaoModel.SENSOR_COLUMNS
            ]
        except Exception as e:
            raise e
        finally:
            if conn and conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()

    @staticmethod
    def get_history_summary(sensor_id, gateway_id, inicio=None, fim=None):
        """Bound chart payloads to 1000 time buckets; stats use the full dataset."""
        conn = cursor = None
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor(dictionary=True)
            gateways = gateway_query_values(sensor_id, gateway_id)
            placeholders = ', '.join(['%s'] * len(gateways))
            where = f'sensor_id = %s AND gateway_id IN ({placeholders})'
            params = [sensor_id, *gateways]
            if inicio and fim:
                where += ' AND data_hora BETWEEN %s AND %s'
                params.extend([inicio, fim])
            cursor.execute(f'SELECT MIN(UNIX_TIMESTAMP(data_hora)) AS first_ts, '
                           f'MAX(UNIX_TIMESTAMP(data_hora)) AS last_ts, COUNT(*) AS total '
                           f'FROM medicoes WHERE {where}', tuple(params))
            bounds = cursor.fetchone()
            if not bounds or not bounds['total']:
                return {'readings': [], 'total': 0, 'bucket_seconds': 1, 'aggregated': False}
            first = int(bounds['first_ts'])
            width = max(1, (int(bounds['last_ts']) - first) // 1000 + 1)
            temperatures = ', '.join(
                f'AVG(CASE WHEN temp_{channel} <> -127 AND NOT '
                f'(sensor_id = 1 AND temp_{channel} = 85) THEN temp_{channel} END) AS temp_{channel}'
                for channel in MedicaoModel.SENSOR_COLUMNS)
            cursor.execute(
                f'SELECT MIN(data_hora) AS data_hora, MAX(id) AS id, {temperatures}, '
                f'AVG(rssi) AS rssi, COUNT(*) AS sample_count FROM medicoes WHERE {where} '
                'GROUP BY FLOOR((UNIX_TIMESTAMP(data_hora) - %s) / %s) ORDER BY data_hora',
                tuple([*params, first, width]))
            rows = cursor.fetchall()
            for row in rows:
                row['data_hora'] = iso_utc(row['data_hora'])
                row['sensor_id'] = sensor_id
                row['gateway_id'] = gateway_id
                for key in [*(f'temp_{s}' for s in MedicaoModel.SENSOR_COLUMNS), 'rssi']:
                    if row[key] is not None:
                        row[key] = float(row[key])
            return {'readings': rows, 'total': bounds['total'], 'bucket_seconds': width,
                    'aggregated': any(row['sample_count'] > 1 for row in rows)}
        finally:
            if conn and conn.is_connected():
                if cursor:
                    cursor.close()
                conn.close()
