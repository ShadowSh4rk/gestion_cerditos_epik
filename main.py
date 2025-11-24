import asyncio
import random
import numpy as np
import pandas as pd
import json
import traceback
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURACIÓ GLOBAL ---
PREU_KG = 1.56
DIES_SIMULACIO = 15

# --- CLASSES ---

class Farm:
    def __init__(self, data):
        self.id = data['farm_id']
        self.name = data['name']
        self.loc = np.array([float(data['lat']), float(data['lon'])])
        self.inventory = data['total_pigs']
        self.mean_weight = data['mean_weight_kg']
        self.std_dev = data.get('std_weight_kg', self.mean_weight * 0.05)
        self.last_visit_day = -999
        
    def grow_pigs(self):
        if self.inventory > 0:
            self.mean_weight += 0.71 
            
    def get_batch_ready(self, max_kg):
        if self.inventory == 0: return 0, [], 0
        
        avg_weight = self.mean_weight
        if avg_weight <= 0: return 0, [], 0

        max_pigs_space = int(max_kg / avg_weight)
        if max_pigs_space < 1: return 0, [], 0

        num_pigs = min(self.inventory, max_pigs_space)
        if num_pigs <= 0: return 0, [], 0

        weights = np.random.normal(self.mean_weight, self.std_dev, num_pigs)
        return num_pigs, weights.tolist(), np.sum(weights)

    def commit_sale(self, num_pigs):
        self.inventory -= num_pigs
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "lat": self.loc[0].item(), 
            "lon": self.loc[1].item(),
            "inventory": self.inventory,
            "avg_weight": round(self.mean_weight, 2)
        }

# --- SIMULADOR EN TEMPS REAL ---

class RealTimeSimulation:
    def __init__(self):
        self.farms = []
        self.transports = []
        self.slaughterhouse_config = {}
        self.slaughterhouse_loc = np.array([0.0, 0.0]) 
        self.daily_logs = [] 
        self.current_sim_day = 1
        self.data_loaded = False
        
        self.load_data()

    def load_data(self):
        print("--- CARGANDO DATOS ---")
        try:
            if os.path.exists('Dades/slaughterhouses 1.json'):
                with open('Dades/slaughterhouses 1.json', 'r', encoding='utf-8') as f:
                    s_data = json.load(f)
                    self.slaughterhouse_config = s_data[0]
                    self.slaughterhouse_loc = np.array([
                        float(self.slaughterhouse_config['lat']), 
                        float(self.slaughterhouse_config['lon'])
                    ])
                    print(f"✅ Matadero: {self.slaughterhouse_config['name']}")
            else:
                self.slaughterhouse_loc = np.array([41.98, 2.80])
                self.slaughterhouse_config = {'daily_capacity_max': 1800}

            if os.path.exists('Dades/transports 1.json'):
                with open('Dades/transports 1.json', 'r', encoding='utf-8') as f:
                    self.transports = json.load(f)
                    print(f"✅ Transportes: {len(self.transports)} unidades.")

            if os.path.exists('Dades/farms 1.json'):
                with open('Dades/farms 1.json', 'r', encoding='utf-8') as f:
                    farms_data = json.load(f)
                    self.farms = [Farm(f) for f in farms_data]
                    print(f"✅ Granjas: {len(self.farms)} ubicaciones.")
                    self.data_loaded = True
        except Exception as e:
            print(f"❌ Error cargando datos: {e}")

    def calculate_distance(self, loc1, loc2):
        return np.linalg.norm(loc1 - loc2) * 111

    def calculate_economics(self, weights):
        revenue = 0
        penalties = 0
        p15 = self.slaughterhouse_config.get('penalty_15_range', [100, 105, 115, 120])
        p20_low = self.slaughterhouse_config.get('penalty_20_below', 100)
        p20_high = self.slaughterhouse_config.get('penalty_20_above', 120)

        for w in weights:
            val = w * PREU_KG
            penalty_rate = 0
            if (p15[0] <= w < p15[1]) or (p15[2] < w <= p15[3]):
                penalty_rate = 0.15
            elif w < p20_low or w > p20_high:
                penalty_rate = 0.20
            
            loss = val * penalty_rate
            revenue += (val - loss)
            penalties += loss
            
        return revenue, penalties, penalties / revenue if revenue else 0

    def get_best_transport(self, load_kg):
        if not self.transports:
            return {'nom': 'Generic', 'type': 'normal', 'cap': 20000, 'cost_km': 1.25, 'fixed_weekly': 2000}

        suitable = [t for t in self.transports if t['capacity_tons'] * 1000 >= load_kg]
        if not suitable:
            best = max(self.transports, key=lambda x: x['capacity_tons'])
        else:
            best = min(suitable, key=lambda x: x['capacity_tons'])
            
        return {
            'nom': best['transport_id'],
            'type': best['type'],
            'cap': best['capacity_tons'] * 1000, 
            'cost_km': best['cost_per_km'],
            'fixed_weekly': best['weekly_fixed_cost']
        }

    def calculate_trip_metrics(self, route_stops, current_load_kg):
        dist = self.calculate_distance(self.slaughterhouse_loc, route_stops[0]['farm'].loc)
        for i in range(len(route_stops)-1):
            dist += self.calculate_distance(route_stops[i]['farm'].loc, route_stops[i+1]['farm'].loc)
        dist += self.calculate_distance(route_stops[-1]['farm'].loc, self.slaughterhouse_loc)
        
        final_truck = self.get_best_transport(current_load_kg)
        trip_cost_variable = dist * final_truck['cost_km']
        
        return dist, final_truck, trip_cost_variable

    # --- LÓGICA DE ANIMACIÓN CONCURRENTE ---
    async def animate_single_route(self, websocket, route_data, truck_vis_id):
        """
        Anima UN solo camión. Se llamará en paralelo con otros.
        """
        current_loc = self.slaughterhouse_loc
        pigs_on_board = 0
        
        # 1. Recorrido de IDA (parada por parada)
        for stop in route_data['route_stops']:
            farm_obj = stop['farm']
            pigs_picked = stop['pigs_count']
            
            # Movimiento hacia la granja
            steps = 20
            lat_steps = np.linspace(current_loc[0], farm_obj.loc[0], steps)
            lon_steps = np.linspace(current_loc[1], farm_obj.loc[1], steps)
            
            for i in range(steps):
                await websocket.send_json({
                    "type": "TRUCK_UPDATE",
                    "truck_id": truck_vis_id,
                    "position": [lat_steps[i].item(), lon_steps[i].item()],
                    "pigs_on_board": pigs_on_board,
                    "status": "MOVING_TO_FARM"
                })
                await asyncio.sleep(0.05) # Velocidad de animación
            
            # LLEGADA A LA GRANJA: Cargar y actualizar Inventario Visualmente
            pigs_on_board += pigs_picked
            await websocket.send_json({
                "type": "TRUCK_UPDATE",
                "truck_id": truck_vis_id,
                "position": [farm_obj.loc[0].item(), farm_obj.loc[1].item()],
                "pigs_on_board": pigs_on_board,  # ahora sí muestra los cerdos reales
                "status": "LOADED"
            })
            current_loc = farm_obj.loc
            
            # --- UPDATE VITAL: Notificar al frontend que esta granja ha perdido cerdos AHORA ---
            await websocket.send_json({
                "type": "FARM_UPDATE",
                "farm_id": farm_obj.id,
                "farm_name": farm_obj.name,
                "new_inventory": stop['inventory_after_pickup'],
                "num_pigs_loaded": stop['pigs_loaded_today'],
                "avg_weight": stop['avg_weight']
            })
            
            # Pequeña pausa de carga
            await asyncio.sleep(0.2)

        # 2. Recorrido de VUELTA (Matadero)
        steps_return = 20
        lat_steps = np.linspace(current_loc[0], self.slaughterhouse_loc[0], steps_return)
        lon_steps = np.linspace(current_loc[1], self.slaughterhouse_loc[1], steps_return)
        
        for i in range(steps_return):
            await websocket.send_json({
                "type": "TRUCK_UPDATE",
                "truck_id": truck_vis_id,
                "position": [lat_steps[i].item(), lon_steps[i].item()],
                "pigs_on_board": pigs_on_board,
                "status": "RETURNING"
            })
            await asyncio.sleep(0.05)
            
        # 3. Llegada Final
        await websocket.send_json({
            "type": "TRUCK_ARRIVED",
            "truck_id": truck_vis_id,
            "pigs_delivered": route_data['route_pigs_count'],
            "metrics_trip": {"revenue": round(route_data['rev'], 2), "cost": round(route_data['trip_cost_variable'], 2)}
        })


    async def run_day_stream(self, websocket, day):
        print(f"\n{'='*40}\n🚛 DIA {day} - PLANIFICANDO LOGÍSTICA\n{'='*40}")

        daily_revenue = 0
        daily_transport_cost_var = 0
        daily_fixed_costs = 0
        pigs_processed = 0
        
        daily_capacity = self.slaughterhouse_config.get('daily_capacity_max', 1800)

        # 1. Crecimiento
        for f in self.farms: f.grow_pigs()
        
        # 2. Mapa Inicial
        await websocket.send_json({
            "type": "INIT_FARMS",
            "farms": [f.to_dict() for f in self.farms],
            "slaughterhouse": [self.slaughterhouse_loc[0].item(), self.slaughterhouse_loc[1].item()]
        })

        # --- FASE 1: PLANIFICACIÓN PURA (Matemática) ---
        # Calculamos TODAS las rutas del día ANTES de empezar a animar para optimizar
        
        available_farms = [f for f in self.farms if (day - f.last_visit_day) >= 7 and f.inventory > 0]
        available_farms.sort(key=lambda x: x.mean_weight, reverse=True)
        
        planned_routes = [] # Aquí guardaremos todas las rutas a ejecutar
        
        while pigs_processed < daily_capacity and len(available_farms) > 0:
            max_truck_cap_kg = 20000 
            current_load_kg = 0
            
            # Estructura temporal para la ruta
            route_stops_data = [] # Guardaremos {farm: obj, pigs: int, inventory_after: int}
            route_weights = []
            
            # Llenar 1 camión
            stops_count = 0
            while stops_count < 3 and current_load_kg < max_truck_cap_kg and len(available_farms) > 0:
                target_farm = available_farms.pop(0) # Extraer la mejor disponible
                space_kg = max_truck_cap_kg - current_load_kg
                
                num, weights, total_w = target_farm.get_batch_ready(space_kg)
                
                if num > 0:
                    # Actualizamos datos internos YA (Commit)
                    target_farm.commit_sale(num)
                    target_farm.last_visit_day = day
                    
                    route_stops_data.append({
                        'farm': target_farm,
                        'pigs_count': num,
                        'inventory_after_pickup': target_farm.inventory,
                        'pigs_loaded_today': num,                   # ✅ fix
                        'avg_weight': round(np.mean(weights), 2)   # ✅ optional
                    })
                    
                    current_load_kg += total_w
                    route_weights.extend(weights)
                    stops_count += 1
                
                # Si no se visita (num=0), ya se ha hecho pop, así que "pasa turno" hoy.
            
            if not route_stops_data:
                break
            
            # Cálculos de la ruta cerrada
            route_pigs_count = len(route_weights)
            dist, final_truck, trip_cost_variable = self.calculate_trip_metrics(route_stops_data, current_load_kg)
            rev, pen, pen_ratio = self.calculate_economics(route_weights)
            
            # Acumuladores del día
            pigs_processed += route_pigs_count
            daily_revenue += rev
            daily_transport_cost_var += trip_cost_variable
            daily_fixed_costs += (final_truck['fixed_weekly'] / 5.0)
            
            # Guardamos la ruta planificada para ejecutarla visualmente
            planned_routes.append({
                'route_stops': route_stops_data,
                'route_pigs_count': route_pigs_count,
                'current_load_kg': current_load_kg,
                'dist': dist,
                'final_truck': final_truck,
                'trip_cost_variable': trip_cost_variable,
                'rev': rev,
                'pen': pen
            })

        print(f"📊 Rutas planificadas: {len(planned_routes)}. Procesando visualización paralela...")

        # --- FASE 2: EJECUCIÓN VISUAL (Logística Paralela) ---
        # Ejecutaremos las rutas en "batches" (lotes) según el número de camiones disponibles
        # Si tenemos 5 camiones, lanzamos 5 rutas a la vez.
        
        available_truck_count = len([t for t in self.transports if t['type'] == 'normal']) or 3 # Por defecto 3 si no carga
        
        # Dividir planned_routes en trozos (chunks)
        chunked_routes = [planned_routes[i:i + available_truck_count] for i in range(0, len(planned_routes), available_truck_count)]
        
        total_trips_visual = 0
        
        for batch_index, batch in enumerate(chunked_routes):
            print(f" 🚀 Lanzando oleada {batch_index + 1} con {len(batch)} camiones simultáneos.")
            
            tasks = []
            for i, route in enumerate(batch):
                total_trips_visual += 1
                # ID visual único para que el frontend distinga los camiones
                truck_vis_id = f"T{total_trips_visual}-{route['final_truck']['nom']}"
                
                # Creamos la tarea asíncrona pero NO la esperamos individualmente
                tasks.append(self.animate_single_route(websocket, route, truck_vis_id))
            
            # Esperamos a que TODA la oleada termine antes de lanzar la siguiente
            # (Opcional: se podría hacer más fluido, pero por orden visual es mejor así)
            await asyncio.gather(*tasks)
            
            # Pequeña pausa entre oleadas
            await asyncio.sleep(0.5)

        # --- RESUMEN FINAL DEL DÍA ---
        daily_profit = daily_revenue - daily_transport_cost_var - daily_fixed_costs
        
        log_entry = {
            'Dia': day,
            'Porcs Processats': pigs_processed,
            'Camions Usats': len(planned_routes),
            'Ingressos Nets': round(daily_revenue, 2),
            'Costos Var. Transp': round(daily_transport_cost_var, 2),
            'Costos Fixos': round(daily_fixed_costs, 2),
            'Benefici Net Diari': round(daily_profit, 2)
        }
        
        self.daily_logs.append(log_entry)
        print(f"🏁 FIN DIA {day}. Beneficio: {daily_profit:.2f}€")
        
        #METRICAS DEL MATADERO
        # n porcs sacrificats
        total_pigs_delivered = sum(route['route_pigs_count'] for route in planned_routes)
        #pes viu total
        total_live_weight = sum(route['current_load_kg'] for route in planned_routes)
        #pes total de canals
        total_carcass_weight = total_live_weight * 0.75
        #pes viu mitja
        avg_live_weight = total_live_weight / total_pigs_delivered if total_pigs_delivered > 0 else 0
        #pes mitja de canal
        avg_carcass_weight = total_carcass_weight / total_pigs_delivered if total_pigs_delivered > 0 else 0
        #capacitat d'operacio
        capacity_utilization = total_pigs_delivered / self.slaughterhouse_config.get('daily_capacity_max', 1800)

        slaughterhouse_metrics = {
            "pigs_delivered": total_pigs_delivered,
            "live_weight_total": round(total_live_weight, 2),
            "carcass_weight_total": round(total_carcass_weight, 2),
            "avg_live_weight": round(avg_live_weight, 2),
            "avg_carcass_weight": round(avg_carcass_weight, 2),
            "capacity_utilization": round(capacity_utilization, 2)
        }

        #ENVIAMOS LAS METRICAS DEL MATADERO
        await websocket.send_json({
            "type": "SLAUGHTERHOUSE_UPDATE",
            "metrics": slaughterhouse_metrics
        })

        #TRUCK METRICS

        truck_metrics_list = []
        for idx, route in enumerate(planned_routes, start=1):
            truck_id = f"T{idx}-{route['final_truck']['nom']}"
            truck_metrics_list.append({
                "truck_id": truck_id,
                "load_kg": round(route['current_load_kg'], 2),
                "num_pigs": route['route_pigs_count'],
                "avg_live_weight": round(route['current_load_kg'] / route['route_pigs_count'], 2) if route['route_pigs_count'] else 0,
                "farms_visited": len(route['route_stops'])
            })

        #ENVIAMOS LAS METRICAS DE CAMION
        await websocket.send_json({
            "type": "TRUCKS_UPDATE",
            "trucks": truck_metrics_list
        })

        #ENVIAMOS EL RESUMEN DIARIO
        await websocket.send_json({
            "type": "DAILY_SUMMARY",
            "summary": log_entry,
            "cumulative_profit": round(sum(log['Benefici Net Diari'] for log in self.daily_logs), 2)
        })

# --- API CONFIG ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sim_instance = RealTimeSimulation()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ Cliente WebSocket conectado.")
    
    try:
        if sim_instance.current_sim_day > DIES_SIMULACIO or not sim_instance.data_loaded:
             sim_instance.current_sim_day = 1
             sim_instance.daily_logs = []
             sim_instance.farms = []
             sim_instance.load_data()

        if not sim_instance.farms:
             await websocket.send_json({"type": "ERROR", "msg": "No se han cargado granjas."})
             return

        while sim_instance.current_sim_day <= DIES_SIMULACIO:
            await sim_instance.run_day_stream(websocket, day=sim_instance.current_sim_day)
            sim_instance.current_sim_day += 1
            
            if sim_instance.current_sim_day <= DIES_SIMULACIO:
                await websocket.send_json({"type": "END_OF_SIM", "msg": "Esperando siguiente día..."})
                await asyncio.sleep(2) 
            else:
                await websocket.send_json({"type": "SIMULATION_COMPLETE", "msg": "Simulación finalizada."})

    except WebSocketDisconnect:
        print("🔌 Cliente desconectado.")
    except Exception as e:
        print(f"❌ ERROR CRÍTICO: {e}")
        traceback.print_exc()