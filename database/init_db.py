from .connection import engine, SessionLocal
from .models import Base, Vessel, TradeRoute, ThreatAlert, RiskLog, GeneratedReport
from data.sample_data import vessels, trade_routes, threat_alerts
import datetime


def create_database():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Vessel).count() == 0:
            for v in vessels:
                db.add(Vessel(
                    name=v['name'],
                    position_lat=v['position_lat'],
                    position_lon=v['position_lon'],
                    status=v['status'],
                ))

        if db.query(TradeRoute).count() == 0:
            for r in trade_routes:
                db.add(TradeRoute(
                    origin_port=r['origin_port'],
                    destination_port=r['destination_port'],
                    risk_level=r['risk_level'],
                    distance=r['distance'],
                ))

        if db.query(ThreatAlert).count() == 0:
            for a in threat_alerts:
                db.add(ThreatAlert(
                    title=a['title'],
                    description=a['description'],
                    severity=a['severity'],
                    location=a['location'],
                ))

        if db.query(RiskLog).count() == 0:
            for i in range(20):
                route_id = (i % 5) + 1
                risk_score = 5 + (i % 5)
                db.add(RiskLog(
                    route_id=route_id,
                    risk_score=risk_score,
                    timestamp=datetime.datetime.utcnow() - datetime.timedelta(days=i),
                ))

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    create_database()
    print("Database created and seeded successfully.")
