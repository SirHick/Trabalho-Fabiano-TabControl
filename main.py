"""
API para receber informações de bateria enviadas por tablets.

Instalar:  pip install fastapi uvicorn
Rodar:     uvicorn main:app --host 0.0.0.0 --port 8000
Docs:      http://localhost:8000/docs
"""
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DB_PATH", "battery.db")

app = FastAPI(title="Battery API", version="1.0.0")


# ---------- Banco de dados (SQLite) ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS battery_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                temperature REAL,
                voltage REAL,
                health TEXT,
                device_time TEXT,
                received_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_device_time "
            "ON battery_readings (device_id, received_at)"
        )


init_db()


# ---------- Modelos ----------
class BatteryReport(BaseModel):
    device_id: str = Field(..., min_length=1, examples=["tablet-001"])
    level: int = Field(..., ge=0, le=100, description="Nível da bateria em %")
    temperature: Optional[float] = Field(None, description="Temperatura em °C")
    voltage: Optional[float] = Field(None, description="Tensão em V")
    health: Optional[str] = Field(None, examples=["good"])
    timestamp: Optional[datetime] = Field(
        None, description="Horário da leitura no tablet (ISO 8601)"
    )


# ---------- Endpoints ----------
@app.post("/battery", status_code=201)
def receive_battery(report: BatteryReport):
    received_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO battery_readings
            (device_id, level, temperature, voltage, health,
             device_time, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.device_id,
                report.level,
                report.temperature,
                report.voltage,
                report.health,
                report.timestamp.isoformat() if report.timestamp else None,
                received_at,
            ),
        )
    return {"status": "ok", "id": cur.lastrowid, "received_at": received_at}


@app.get("/devices")
def devices():
    """Última leitura de cada dispositivo."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM battery_readings WHERE id IN "
            "(SELECT MAX(id) FROM battery_readings GROUP BY device_id) "
            "ORDER BY device_id"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/battery/{device_id}/latest")
def latest(device_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM battery_readings WHERE device_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dispositivo sem leituras")
    return dict(row)


@app.get("/battery/{device_id}/history")
def history(device_id: str, limit: int = Query(100, ge=1, le=1000)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM battery_readings WHERE device_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/health")
def health_check():
    return {"status": "ok"} 
