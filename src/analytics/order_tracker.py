"""
Отслеживание ордеров - мониторинг изменений и жизненного цикла
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import hashlib

from src.exchanges.base_exchange import BaseExchange
from src.utils.logger import get_component_logger

logger = get_component_logger("order_tracker")


@dataclass
class OrderSnapshot:
    """Снимок состояния ордера в конкретный момент времени"""
    timestamp: datetime
    price: float
    quantity: float
    usd_value: float
    distance_percent: float
    
    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)


@dataclass  
class TrackedOrder:
    """Отслеживаемый ордер с полной историей изменений"""
    order_hash: str
    symbol: str
    order_type: str  # ASK или BID
    initial_price: float
    initial_quantity: float
    initial_usd_value: float
    first_seen: datetime
    
    # История изменений
    snapshots: List[OrderSnapshot] = field(default_factory=list)
    
    # Текущее состояние
    current_price: float = 0.0
    current_quantity: float = 0.0
    current_usd_value: float = 0.0
    last_seen: datetime = None
    
    # Статистика
    scan_count: int = 0
    is_alive: bool = True
    died_at: Optional[datetime] = None
    lifetime_seconds: float = 0.0
    
    # Флаги состояния
    moved_to_hot_pool: bool = False
    is_persistent: bool = False
    
    def __post_init__(self):
        if self.first_seen.tzinfo is None:
            self.first_seen = self.first_seen.replace(tzinfo=timezone.utc)
        if self.last_seen and self.last_seen.tzinfo is None:
            self.last_seen = self.last_seen.replace(tzinfo=timezone.utc)
    
    def add_snapshot(self, price: float, quantity: float, current_price: float):
        """Добавить новый снимок состояния ордера"""
        now = datetime.now(timezone.utc)
        usd_value = price * quantity
        distance_percent = abs(price - current_price) / current_price * 100
        
        snapshot = OrderSnapshot(
            timestamp=now,
            price=price,
            quantity=quantity,
            usd_value=usd_value,
            distance_percent=distance_percent
        )
        
        self.snapshots.append(snapshot)
        self.current_price = price
        self.current_quantity = quantity
        self.current_usd_value = usd_value
        self.last_seen = now
        self.scan_count += 1
        
        # Обновляем время жизни
        self.lifetime_seconds = (now - self.first_seen).total_seconds()
        
        # Определяем постоянство (живет больше 30 секунд)
        if self.lifetime_seconds > 30:
            self.is_persistent = True
    
    def mark_as_dead(self):
        """Пометить ордер как исчезнувший"""
        if self.is_alive:
            self.is_alive = False
            self.died_at = datetime.now(timezone.utc)
    
    def calculate_survival_rate(self, threshold: float = 0.7) -> float:
        """
        Рассчитать коэффициент выживания ордера
        
        Args:
            threshold: Порог потери объема для считания "смерти"
            
        Returns:
            Коэффициент выживания (0.0 - 1.0)
        """
        if not self.snapshots:
            return 1.0
        
        initial_value = self.initial_usd_value
        current_value = self.current_usd_value
        
        if initial_value <= 0:
            return 1.0
        
        return min(current_value / initial_value, 1.0)
    
    def get_growth_trend(self) -> str:
        """
        Определить тренд изменения размера ордера
        
        Returns:
            "increasing", "decreasing", "stable"
        """
        if len(self.snapshots) < 3:
            return "stable"
        
        # Сравниваем последние 3 снимка
        recent_values = [s.usd_value for s in self.snapshots[-3:]]
        
        if recent_values[-1] > recent_values[0] * 1.05:
            return "increasing"
        elif recent_values[-1] < recent_values[0] * 0.95:
            return "decreasing"
        else:
            return "stable"
    
    def get_stability_score(self) -> float:
        """
        Рассчитать коэффициент стабильности ордера
        
        Returns:
            Коэффициент стабильности (0.0 - 1.0)
        """
        if len(self.snapshots) < 2:
            return 1.0
        
        # Рассчитываем коэффициент вариации размера ордера
        values = [s.usd_value for s in self.snapshots]
        mean_value = sum(values) / len(values)
        
        if mean_value <= 0:
            return 0.0
        
        variance = sum((v - mean_value) ** 2 for v in values) / len(values)
        coefficient_of_variation = (variance ** 0.5) / mean_value
        
        # Инвертируем - меньше вариации = выше стабильность
        return max(0.0, 1.0 - coefficient_of_variation)


class OrderTracker:
    """Система отслеживания ордеров"""
    
    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange
        self.logger = logger
        
        # Хранилище отслеживаемых ордеров
        self.tracked_orders: Dict[str, TrackedOrder] = {}
        self.dead_orders: Dict[str, TrackedOrder] = {}
        
        # Статистика
        self.total_orders_tracked = 0
        self.total_orders_died = 0
        self.orders_moved_to_hot = 0
        
        # Настройки
        self.survival_threshold = 0.7  # Порог выживания (70%)
        self.max_dead_orders = 1000    # Максимум мертвых ордеров в памяти
    
    def generate_order_hash(self, symbol: str, price: float, quantity: float, 
                          order_type: str) -> str:
        """
        Генерировать хэш для ордера (совместимо с первичным сканнером)
        
        Args:
            symbol: Торговая пара
            price: Цена ордера
            quantity: Количество
            order_type: Тип ордера (ASK/BID)
            
        Returns:
            Уникальный хэш ордера
        """
        hash_string = f"{symbol}{price}{quantity}{order_type}{datetime.now().isoformat()}"
        hash_value = hashlib.md5(hash_string.encode()).hexdigest()[:12]
        return f"{symbol[:6]}-{hash_value}"
    
    def start_tracking_order(self, symbol: str, price: float, quantity: float, 
                           order_type: str, current_price: float,
                           order_hash: str = None) -> str:
        """
        Начать отслеживание нового ордера
        
        Args:
            symbol: Торговая пара
            price: Цена ордера
            quantity: Количество
            order_type: Тип ордера
            current_price: Текущая рыночная цена
            order_hash: Готовый хэш (если есть)
            
        Returns:
            Хэш ордера для отслеживания
        """
        if not order_hash:
            order_hash = self.generate_order_hash(symbol, price, quantity, order_type)
        
        if order_hash in self.tracked_orders:
            # Ордер уже отслеживается - обновляем
            self.update_tracked_order(order_hash, price, quantity, current_price)
            return order_hash
        
        # Создаем новый отслеживаемый ордер
        now = datetime.now(timezone.utc)
        usd_value = price * quantity
        
        tracked_order = TrackedOrder(
            order_hash=order_hash,
            symbol=symbol,
            order_type=order_type,
            initial_price=price,
            initial_quantity=quantity,
            initial_usd_value=usd_value,
            first_seen=now,
            current_price=price,
            current_quantity=quantity,
            current_usd_value=usd_value,
            last_seen=now
        )
        
        # Добавляем начальный снимок
        tracked_order.add_snapshot(price, quantity, current_price)
        
        # Сохраняем ордер
        self.tracked_orders[order_hash] = tracked_order
        self.total_orders_tracked += 1
        
        self.logger.debug(f"Начато отслеживание ордера {order_hash} ({symbol})")
        return order_hash
    
    def update_tracked_order(self, order_hash: str, price: float, 
                           quantity: float, current_price: float) -> bool:
        """
        Обновить информацию об отслеживаемом ордере
        
        Args:
            order_hash: Хэш ордера
            price: Новая цена ордера
            quantity: Новое количество
            current_price: Текущая рыночная цена
            
        Returns:
            True если ордер обновлен, False если не найден
        """
        if order_hash not in self.tracked_orders:
            return False
        
        tracked_order = self.tracked_orders[order_hash]
        
        # Добавляем новый снимок
        tracked_order.add_snapshot(price, quantity, current_price)
        
        # Проверяем выживание ордера
        survival_rate = tracked_order.calculate_survival_rate(self.survival_threshold)
        
        if survival_rate < self.survival_threshold:
            # Ордер "умер" - потерял слишком много объема
            self._mark_order_dead(order_hash, "volume_loss")
            return False
        
        return True
    
    def check_order_death(self, order_hash: str, reason: str = "disappeared"):
        """
        Отметить ордер как исчезнувший
        
        Args:
            order_hash: Хэш ордера
            reason: Причина исчезновения
        """
        if order_hash in self.tracked_orders:
            self._mark_order_dead(order_hash, reason)
    
    def _mark_order_dead(self, order_hash: str, reason: str):
        """Переместить ордер в список мертвых"""
        if order_hash not in self.tracked_orders:
            return
        
        tracked_order = self.tracked_orders[order_hash]
        tracked_order.mark_as_dead()
        
        # Перемещаем в мертвые ордера
        self.dead_orders[order_hash] = tracked_order
        del self.tracked_orders[order_hash]
        
        self.total_orders_died += 1
        
        self.logger.debug(f"Ордер {order_hash} помечен как мертвый: {reason}")
        
        # Ограничиваем размер истории мертвых ордеров
        if len(self.dead_orders) > self.max_dead_orders:
            # Удаляем самые старые
            oldest_hashes = sorted(self.dead_orders.keys(), 
                                 key=lambda h: self.dead_orders[h].died_at or datetime.min)[:100]
            for old_hash in oldest_hashes:
                del self.dead_orders[old_hash]
    
    def get_tracked_order(self, order_hash: str) -> Optional[TrackedOrder]:
        """Получить отслеживаемый ордер по хэшу"""
        return self.tracked_orders.get(order_hash)
    
    def get_orders_by_symbol(self, symbol: str) -> List[TrackedOrder]:
        """Получить все отслеживаемые ордера по символу"""
        return [order for order in self.tracked_orders.values() 
                if order.symbol == symbol]
    
    def get_persistent_orders(self, min_lifetime_seconds: int = 60) -> List[TrackedOrder]:
        """
        Получить постоянные ордера (живущие дольше заданного времени)
        
        Args:
            min_lifetime_seconds: Минимальное время жизни
            
        Returns:
            Список постоянных ордеров, готовых к переводу в горячий пул
        """
        persistent_orders = []
        
        for order in self.tracked_orders.values():
            if (order.lifetime_seconds >= min_lifetime_seconds and 
                not order.moved_to_hot_pool):
                persistent_orders.append(order)
        
        return persistent_orders
    
    def mark_order_moved_to_hot_pool(self, order_hash: str):
        """Отметить ордер как переведенный в горячий пул"""
        if order_hash in self.tracked_orders:
            self.tracked_orders[order_hash].moved_to_hot_pool = True
            self.orders_moved_to_hot += 1
            
            self.logger.debug(f"Ордер {order_hash} переведен в горячий пул")
    
    def cleanup_old_data(self, max_age_hours: int = 24):
        """
        Очистка старых данных
        
        Args:
            max_age_hours: Максимальный возраст данных в часах
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        # Очищаем старые мертвые ордера
        to_remove = []
        for order_hash, order in self.dead_orders.items():
            if order.died_at and order.died_at < cutoff_time:
                to_remove.append(order_hash)
        
        for order_hash in to_remove:
            del self.dead_orders[order_hash]
        
        if to_remove:
            self.logger.debug(f"Удалено {len(to_remove)} старых мертвых ордеров")
    
    def get_statistics(self) -> Dict:
        """Получить статистику отслеживания ордеров"""
        now = datetime.now(timezone.utc)
        
        # Статистика живых ордеров
        alive_orders = list(self.tracked_orders.values())
        avg_lifetime = 0.0
        if alive_orders:
            avg_lifetime = sum(order.lifetime_seconds for order in alive_orders) / len(alive_orders)
        
        # Статистика мертвых ордеров за последние 24 часа
        cutoff_24h = now - timedelta(hours=24)
        recent_deaths = [order for order in self.dead_orders.values() 
                        if order.died_at and order.died_at >= cutoff_24h]
        
        return {
            "tracked_orders_count": len(self.tracked_orders),
            "dead_orders_count": len(self.dead_orders),
            "total_orders_tracked": self.total_orders_tracked,
            "total_orders_died": self.total_orders_died,
            "orders_moved_to_hot": self.orders_moved_to_hot,
            "average_lifetime_seconds": avg_lifetime,
            "recent_deaths_24h": len(recent_deaths),
            "survival_rate_24h": (
                1.0 - len(recent_deaths) / max(self.total_orders_tracked, 1)
            ) if self.total_orders_tracked > 0 else 0.0
        }
