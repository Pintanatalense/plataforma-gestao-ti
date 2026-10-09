import app.main
from app.database import Base
print("StockItem in registry:", "StockItem" in Base.registry._class_registry)
