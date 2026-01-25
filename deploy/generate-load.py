#!/usr/bin/env python3

import aiohttp
import asyncio
import random
import sys
from typing import Optional

BASE_URL = "http://muffin-wallet.com"
NUM_REQUESTS = 100
SLEEP_TIME = 0.5
CONCURRENT_REQUESTS = 10

class LoadGenerator:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.success_count = 0
        self.error_count = 0
        self.wallets_by_type = {}  
        
    async def check_api_availability(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/actuator/health", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    return response.status == 200
        except Exception:
            return False
    
    async def create_wallet(self, session: aiohttp.ClientSession, owner_name: str, wallet_type: str) -> Optional[tuple]:
        try:
            async with session.post(
                f"{self.base_url}/v1/muffin-wallets",
                json={
                    "owner_name": owner_name,
                    "type": wallet_type
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    wallet = await response.json()
                    wallet_id = wallet.get('id')
                    if wallet_id:
                        return (wallet_id, wallet_type)
                return None
        except Exception as e:
            print(f"Ошибка при создании кошелька: {e}")
            return None
    
    async def get_wallets(self, session: aiohttp.ClientSession) -> bool:
        try:
            async with session.get(
                f"{self.base_url}/v1/muffin-wallets",
                params={"page": "0", "size": "1000"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
        except Exception:
            return False
    
    async def get_wallet(self, session: aiohttp.ClientSession, wallet_id: str) -> bool:
        try:
            async with session.get(
                f"{self.base_url}/v1/muffin-wallet/{wallet_id}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
        except Exception:
            return False
    
    async def create_transaction(self, session: aiohttp.ClientSession, from_wallet_id: str, to_wallet_id: str, amount: float) -> bool:
        try:
            async with session.post(
                f"{self.base_url}/v1/muffin-wallet/{from_wallet_id}/transaction",
                json={
                    "to_muffin_wallet_id": to_wallet_id,
                    "amount": amount
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                return response.status == 200
        except Exception:
            return False
    
    async def generate_error_requests(self, session: aiohttp.ClientSession):
        try:
            async with session.get(f"{self.base_url}/v1/nonexistent-endpoint", timeout=aiohttp.ClientTimeout(total=5)) as response:
                pass
        except Exception:
            pass
        
        try:
            async with session.post(
                f"{self.base_url}/v1/muffin-wallets",
                json={"invalid": "data"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                pass
        except Exception:
            pass
    
    async def perform_request_batch(self, session: aiohttp.ClientSession):
        if await self.get_wallets(session):
            self.success_count += 1
        else:
            self.error_count += 1
        
        wallet_types = list(self.wallets_by_type.keys())
        if len(wallet_types) >= 2:
            from_type, to_type = random.sample(wallet_types, 2)
            
            from_wallet = random.choice(self.wallets_by_type[from_type])
            to_wallet = random.choice(self.wallets_by_type[to_type])
            
            amount = round(random.uniform(1, 1000), 2)
            
            if await self.create_transaction(session, from_wallet, to_wallet, amount):
                self.success_count += 1
            else:
                self.error_count += 1
        else:
            self.error_count += 1
        
        all_wallets = [wid for wallets in self.wallets_by_type.values() for wid in wallets]
        wallet_to_check = random.choice(all_wallets)
        if await self.get_wallet(session, wallet_to_check):
            self.success_count += 1
        else:
            self.error_count += 1
    
    async def run(self, num_requests: int, sleep_time: float, concurrent: int):
        print("=" * 50)
        print("Генерация нагрузки на muffin-wallet (асинхронно)")
        print("=" * 50)
        print(f"URL: {self.base_url}")
        print(f"Количество запросов: {num_requests}")
        print(f"Задержка между запросами: {sleep_time}s")
        print(f"Одновременных запросов: {concurrent}")
        print("=" * 50)
        print()
        
        print("Проверяю доступность API...")
        if not await self.check_api_availability():
            print("ОШИБКА: API недоступен")
            print("Убедитесь, что:")
            print("  1. muffin-wallet развернут в Kubernetes")
            print("  2. Запущен minikube tunnel (sudo minikube tunnel)")
            print("  3. В /etc/hosts прописано: 127.0.0.1 muffin-wallet.com")
            sys.exit(1)
        
        print("API доступен")
        print()
        
        wallet_pool_size = max(20, concurrent * 2) 
        print(f"Создаю пул из {wallet_pool_size} кошельков...")
        
        wallet_types = ["CARAMEL", "CHOKOLATE"]
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            for i in range(wallet_pool_size):
                wallet_type = wallet_types[i % 2]
                tasks.append(self.create_wallet(session, f"Load Test Wallet {i+1}", wallet_type))
            
            results = await asyncio.gather(*tasks)
            
            self.wallets_by_type = {"CARAMEL": [], "CHOKOLATE": []}
            for result in results:
                if result is not None:
                    wallet_id, wallet_type = result
                    self.wallets_by_type[wallet_type].append(wallet_id)
            
            total_wallets = sum(len(wallets) for wallets in self.wallets_by_type.values())
            
            if total_wallets < 2 or any(len(wallets) == 0 for wallets in self.wallets_by_type.values()):
                print("ОШИБКА: Не удалось создать достаточно кошельков каждого типа")
                sys.exit(1)
            
            print(f"Создано {total_wallets} кошельков:")
            for wtype, wallets in self.wallets_by_type.items():
                print(f"  - {wtype}: {len(wallets)} кошельков")
            print()
            
            print("Начинаю генерацию запросов...")
            print()
            
            for batch_num in range(0, num_requests, concurrent):
                tasks = []
                batch_size = min(concurrent, num_requests - batch_num)
                
                for i in range(batch_size):
                    request_num = batch_num + i + 1
                    tasks.append(self.perform_request_batch(session))
                    
                    if request_num % 10 == 0:
                        tasks.append(self.generate_error_requests(session))
                
                await asyncio.gather(*tasks)
                
                completed = batch_num + batch_size
                progress = (completed * 100) // num_requests
                print(f"  Прогресс: {progress}% ({completed}/{num_requests} запросов)")
                
                if completed < num_requests:
                    await asyncio.sleep(sleep_time)
        
        print()
        print("=" * 50)
        print("Генерация нагрузки завершена!")
        print("=" * 50)
        print(f"Успешных запросов: {self.success_count}")
        print(f"Ошибок: {self.error_count}")
        print()
        print("Проверьте метрики в Prometheus:")
        print("  1. Откройте http://prometheus.local")
        print("  2. Выполните PromQL запросы из README.md")
        print()
        print("=" * 50)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Генератор нагрузки для muffin-wallet (асинхронный)')
    parser.add_argument('--url', default=BASE_URL, help='Base URL приложения')
    parser.add_argument('--requests', type=int, default=NUM_REQUESTS, help='Количество запросов')
    parser.add_argument('--sleep', type=float, default=SLEEP_TIME, help='Задержка между запросами (сек)')
    parser.add_argument('--concurrent', type=int, default=CONCURRENT_REQUESTS, help='Количество одновременных запросов')
    
    args = parser.parse_args()
    
    generator = LoadGenerator(args.url)
    asyncio.run(generator.run(args.requests, args.sleep, args.concurrent))
