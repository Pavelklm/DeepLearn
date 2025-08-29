"""
Система кэширования - хранение часто используемых данных
"""

import json
import asyncio
from typing import Dict, Any, Optional, Callable, Union
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pickle
import hashlib

from src.utils.logger import get_component_logger

logger = get_component_logger("cache")


class Cache:
    """Система кэширования с TTL и персистентным хранением"""
    
    def __init__(self, cache_dir: str = "data/cache", default_ttl: int = 300):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        self.default_ttl = default_ttl  # Время жизни по умолчанию (секунды)
        
        # In-memory кэш
        self._memory_cache: Dict[str, Dict] = {}
        
        # Настройки
        self.max_memory_items = 1000
        self.cleanup_interval = 600  # Очистка каждые 10 минут
        
        # Задача очистки
        self._cleanup_task = None
        self._is_running = False
    
    def start(self):
        """Запуск системы кэширования"""
        if self._is_running:
            return
            
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.debug("Система кэширования запущена")
    
    async def stop(self):
        """Остановка системы кэширования"""
        if not self._is_running:
            return
        
        self._is_running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.debug("Система кэширования остановлена")
    
    def _generate_key(self, namespace: str, key: str) -> str:
        """Генерация ключа кэша"""
        return f"{namespace}:{key}"
    
    def _is_expired(self, item: Dict) -> bool:
        """Проверка истечения срока действия элемента кэша"""
        if "expires_at" not in item:
            return False
        
        return datetime.now(timezone.utc) >= item["expires_at"]
    
    def set(self, namespace: str, key: str, value: Any, ttl: int = None) -> bool:
        """
        Сохранить значение в кэш
        
        Args:
            namespace: Пространство имен
            key: Ключ
            value: Значение
            ttl: Время жизни в секундах (None = default_ttl)
            
        Returns:
            True если успешно сохранено
        """
        try:
            cache_key = self._generate_key(namespace, key)
            ttl = ttl or self.default_ttl
            
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            
            cache_item = {
                "value": value,
                "created_at": datetime.now(timezone.utc),
                "expires_at": expires_at,
                "ttl": ttl,
                "hits": 0
            }
            
            # Сохраняем в memory
            self._memory_cache[cache_key] = cache_item
            
            # Ограничиваем размер memory кэша
            if len(self._memory_cache) > self.max_memory_items:
                self._evict_lru()
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения в кэш {namespace}:{key}: {e}")
            return False
    
    def get(self, namespace: str, key: str) -> Optional[Any]:
        """
        Получить значение из кэша
        
        Args:
            namespace: Пространство имен
            key: Ключ
            
        Returns:
            Значение или None если не найдено/истекло
        """
        try:
            cache_key = self._generate_key(namespace, key)
            
            # Проверяем memory кэш
            if cache_key in self._memory_cache:
                item = self._memory_cache[cache_key]
                
                if self._is_expired(item):
                    del self._memory_cache[cache_key]
                    return None
                
                # Увеличиваем счетчик обращений
                item["hits"] += 1
                return item["value"]
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка получения из кэша {namespace}:{key}: {e}")
            return None
    
    def delete(self, namespace: str, key: str) -> bool:
        """
        Удалить значение из кэша
        
        Args:
            namespace: Пространство имен
            key: Ключ
            
        Returns:
            True если удалено
        """
        try:
            cache_key = self._generate_key(namespace, key)
            
            if cache_key in self._memory_cache:
                del self._memory_cache[cache_key]
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка удаления из кэша {namespace}:{key}: {e}")
            return False
    
    def exists(self, namespace: str, key: str) -> bool:
        """Проверить существование ключа в кэше"""
        try:
            cache_key = self._generate_key(namespace, key)
            
            if cache_key in self._memory_cache:
                item = self._memory_cache[cache_key]
                
                if self._is_expired(item):
                    del self._memory_cache[cache_key]
                    return False
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Ошибка проверки существования {namespace}:{key}: {e}")
            return False
    
    def clear_namespace(self, namespace: str) -> int:
        """
        Очистить все ключи в пространстве имен
        
        Args:
            namespace: Пространство имен для очистки
            
        Returns:
            Количество удаленных элементов
        """
        try:
            prefix = f"{namespace}:"
            to_delete = [key for key in self._memory_cache.keys() if key.startswith(prefix)]
            
            for key in to_delete:
                del self._memory_cache[key]
            
            logger.debug(f"Очищено {len(to_delete)} элементов из namespace {namespace}")
            return len(to_delete)
            
        except Exception as e:
            logger.error(f"Ошибка очистки namespace {namespace}: {e}")
            return 0
    
    def _evict_lru(self):
        """Удаление наименее используемых элементов"""
        if not self._memory_cache:
            return
        
        # Сортируем по количеству обращений и времени создания
        items = list(self._memory_cache.items())
        items.sort(key=lambda x: (x[1]["hits"], x[1]["created_at"]))
        
        # Удаляем 10% наименее используемых
        to_remove = len(items) // 10
        for i in range(to_remove):
            key, _ = items[i]
            del self._memory_cache[key]
    
    async def _cleanup_loop(self):
        """Периодическая очистка истекших элементов"""
        while self._is_running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                self._cleanup_expired()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле очистки кэша: {e}")
    
    def _cleanup_expired(self):
        """Удаление истекших элементов из memory кэша"""
        expired_keys = []
        
        for key, item in self._memory_cache.items():
            if self._is_expired(item):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._memory_cache[key]
        
        if expired_keys:
            logger.debug(f"Удалено {len(expired_keys)} истекших элементов из кэша")
    
    def get_stats(self) -> Dict:
        """Получить статистику кэша"""
        total_hits = sum(item.get("hits", 0) for item in self._memory_cache.values())
        
        # Группировка по namespace
        namespaces = {}
        for key in self._memory_cache.keys():
            namespace = key.split(":", 1)[0]
            namespaces[namespace] = namespaces.get(namespace, 0) + 1
        
        return {
            "memory_items": len(self._memory_cache),
            "total_hits": total_hits,
            "namespaces": namespaces,
            "is_running": self._is_running
        }


class CachedFunction:
    """Декоратор для кэширования результатов функций"""
    
    def __init__(self, cache: Cache, namespace: str, ttl: int = None):
        self.cache = cache
        self.namespace = namespace  
        self.ttl = ttl
    
    def __call__(self, func: Callable):
        def wrapper(*args, **kwargs):
            # Генерируем ключ на основе аргументов
            key_data = str(args) + str(sorted(kwargs.items()))
            key_hash = hashlib.md5(key_data.encode()).hexdigest()[:12]
            key = f"{func.__name__}_{key_hash}"
            
            # Пытаемся получить из кэша
            result = self.cache.get(self.namespace, key)
            if result is not None:
                return result
            
            # Выполняем функцию и кэшируем результат
            result = func(*args, **kwargs)
            self.cache.set(self.namespace, key, result, self.ttl)
            
            return result
        
        return wrapper


# Глобальный экземпляр кэша
_global_cache: Optional[Cache] = None


def get_cache() -> Cache:
    """Получить глобальный экземпляр кэша"""
    global _global_cache
    
    if _global_cache is None:
        from config.main_config import CACHE_CONFIG
        _global_cache = Cache(
            cache_dir=CACHE_CONFIG["cache_directory"],
            default_ttl=CACHE_CONFIG["volatility_cache_ttl"]
        )
        _global_cache.start()
    
    return _global_cache


def cached(namespace: str, ttl: int = None):
    """
    Декоратор для кэширования результатов функций
    
    Args:
        namespace: Пространство имен для кэша
        ttl: Время жизни в секундах
    """
    cache = get_cache()
    return CachedFunction(cache, namespace, ttl)


# Удобные функции для работы с кэшем
def cache_set(namespace: str, key: str, value: Any, ttl: int = None) -> bool:
    """Сохранить значение в глобальный кэш"""
    return get_cache().set(namespace, key, value, ttl)


def cache_get(namespace: str, key: str) -> Optional[Any]:
    """Получить значение из глобального кэша"""
    return get_cache().get(namespace, key)


def cache_delete(namespace: str, key: str) -> bool:
    """Удалить значение из глобального кэша"""
    return get_cache().delete(namespace, key)


def cache_clear(namespace: str) -> int:
    """Очистить namespace в глобальном кэше"""
    return get_cache().clear_namespace(namespace)
