import asyncio
import random
import numpy as np
import pandas as pd
import math
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURACIÓ I CONSTANTS ---
PREU_KG = 1.56
COST_FIX_CAMIO_SETMANAL = 2000
CAPACITAT_ESCORXADOR_DIARIA = 1800
DIES_SIMULACIO = 15 # Definit per saber quan s'acaba la simulació total

CAMIO_PETIT = {'cap': 10000, 'cost_km': 1.15, 'nom': '10T'}
CAMIO_GRAN = {'cap': 20000, 'cost_km': 1.25, 'nom': '20T'}

# --- CLASSES ---

class Farm:
    def __init__(self, id, lat, lon, inventory, mean_weight):
        self.id = id
        self.loc = np.array([lat, lon])
        self.inventory = inventory
        self.mean_weight = mean_weight
        self.std_dev = mean_weight * 0.05
        self.last_visit_day = -999
        
    def grow_pigs(self):
        if self.inventory > 0:
            self.mean_weight += 0.71
            
    def get_batch_ready(self, max_kg):
        if self.inventory == 0: return 0, [], 0
        avg_weight = self.mean_weight
        max_pigs = int(max_kg / avg_weight)
        num_pigs = min(self.inventory, max_pigs)
        weights = np.random.normal(self.mean_weight, self.std_dev, num_pigs)
        return num_pigs, weights.tolist(), np.sum(weights)

    def commit_sale(self, num_pigs):
        self.inventory -= num_pigs
    
    def to_dict(self):
        return {
            "id": self.id,
            "lat": self.loc[0].item(), 
            "lon": self.loc[1].item(),
            "inventory": self.inventory,
            "avg_weight": round(self.mean_weight, 2)
        }

# --- SIMULADOR EN TEMPS REAL (AMB LOGGING) ---

class RealTimeSimulation:
    def __init__(self):
        self.farms = []
        self.slaughterhouse_loc = np.array([41.38, 2.16]) 
        self.generate_data()
        self.daily_logs = [] 
        self.current_sim_day = 1 # Seguidor de dies

    def generate_data(self):
        for i in range(15):
            lat = 41.38 + random.uniform(-0.1, 0.1)
            lon = 2.16 + random.uniform(-0.1, 0.1)
            inv = random.randint(500, 2000)
            w = random.uniform(95, 112)
            self.farms.append(Farm(f"F-{i+1:02d}", lat, lon, inv, w))

    def calculate_distance(self, loc1, loc2):
        return np.linalg.norm(loc1 - loc2) * 111

    def calculate_economics(self, weights):
        revenue = 0
        penalties = 0
        
        for w in weights:
            val = w * PREU_KG
            penalty_rate = 0
            
            if (100 <= w < 105) or (115 < w <= 120):
                penalty_rate = 0.15
            elif w < 100 or w > 120:
                penalty_rate = 0.20
            
            loss = val * penalty_rate
            revenue += (val - loss)
            penalties += loss
            
        return revenue, penalties, penalties / revenue if revenue else 0

    def calculate_trip_metrics(self, route_stops, current_load_kg):
        dist = self.calculate_distance(self.slaughterhouse_loc, route_stops[0].loc)
        for i in range(len(route_stops)-1):
            dist += self.calculate_distance(route_stops[i].loc, route_stops[i+1].loc)
        dist += self.calculate_distance(route_stops[-1].loc, self.slaughterhouse_loc)
        
        final_truck = CAMIO_GRAN if current_load_kg > CAMIO_PETIT['cap'] else CAMIO_PETIT
        trip_cost_variable = dist * final_truck['cost_km'] * (current_load_kg / final_truck['cap'])
        
        return dist, final_truck, trip_cost_variable

    async def animate_travel(self, websocket, start_loc, end_loc, truck_id, load, steps=20):
        lat_steps = np.linspace(start_loc[0], end_loc[0], steps)
        lon_steps = np.linspace(start_loc[1], end_loc[1], steps)
        
        for i in range(steps):
            current_pos = [lat_steps[i].item(), lon_steps[i].item()]
            
            await websocket.send_json({
                "type": "TRUCK_UPDATE",
                "truck_id": truck_id,
                "position": current_pos,
                "pigs_on_board": load,
                "status": "MOVING"
            })
            await asyncio.sleep(0.05) 

    def print_terminal_log_route(self, route_data, trucks_used_count):
        # FUNCIÓ PER IMPRIMIR DETALLS DE LA RUTA A LA TERMINAL
        print(f" > RUTA {trucks_used_count} ({route_data['final_truck']['nom']}):")
        print(f"   - Origen/Stops: {' -> '.join([f.id for f in route_data['route_stops']])}")
        print(f"   - Porcs/Kg: {route_data['route_pigs_count']} porcs | {int(route_data['current_load_kg'])} kg")
        print(f"   - Dist/Cost: {route_data['dist']:.1f} km | Cost Var: {route_data['trip_cost_variable']:.2f} €")
        print(f"   - Ingressos Nets: {route_data['rev']:.2f} € | Penalització: {route_data['pen']:.2f} € ({route_data['pen_ratio']*100:.1f}%)")
        print("-" * 40)

    def print_terminal_log_summary(self, log_entry):
        # FUNCIÓ PER IMPRIMIR EL RESUM DIARI I ACUMULAT A LA TERMINAL
        print(f"\n--- RESUM DIA {log_entry['Dia']} ---")
        print(f"  Total Processat: {log_entry['Porcs Processats']} porcs amb {log_entry['Camions Usats']} camions.")
        print(f"  💸 BENEFICI NET: {log_entry['Benefici Net Diari']:,.2f} €")
        print(f"  (Ingressos: {log_entry['Ingressos Nets']:,.2f} € | Despeses: {log_entry['Costos Var. Transp'] + log_entry['Costos Fixos']:,.2f} €)")
        print(f"--------------------------")
        
        df_results = pd.DataFrame(self.daily_logs)
        if len(self.daily_logs) > 0:
            print(f"\n# LOG ACUMULAT (Dia {log_entry['Dia']} / {DIES_SIMULACIO})")
            print(df_results.to_string(index=False))
            print(f"💰 BENEFICI TOTAL ACUMULAT: {df_results['Benefici Net Diari'].sum():,.2f} €")
            print("#" * 60)


    async def run_day_stream(self, websocket, day):
        # LOG INICI DIA A TERMINAL
        print(f"\n{'='*50}\n🚛 DIA {day} - INICI DE LA PLANIFICACIÓ\n{'='*50}")

        daily_revenue = 0
        daily_transport_cost_var = 0
        trucks_used_count = 0
        pigs_processed = 0

        # Creixement de porcs i enviament d'estat inicial
        for f in self.farms: f.grow_pigs()
        await websocket.send_json({
            "type": "INIT_FARMS",
            "farms": [f.to_dict() for f in self.farms],
            "slaughterhouse": [41.38, 2.16]
        })

        available_farms = [f for f in self.farms if (day - f.last_visit_day) >= 7 and f.inventory > 0]
        available_farms.sort(key=lambda x: x.mean_weight, reverse=True)
        
        # Bucle de Planificació
        while pigs_processed < CAPACITAT_ESCORXADOR_DIARIA and len(available_farms) > 0:
            
            truck_type = CAMIO_GRAN
            current_load_kg = 0
            route_stops = []
            route_weights = []
            
            # Recollida de porcs
            while len(route_stops) < 3 and current_load_kg < truck_type['cap'] and len(available_farms) > 0:
                target_farm = available_farms.pop(0) 
                space_kg = truck_type['cap'] - current_load_kg
                num, weights, total_w = target_farm.get_batch_ready(space_kg)
                
                if num > 0:
                    target_farm.commit_sale(num)
                    target_farm.last_visit_day = day
                    route_stops.append(target_farm)
                    current_load_kg += total_w
                    route_weights.extend(weights)
                
            if not route_stops: continue
            
            route_pigs_count = len(route_weights)
            pigs_processed += route_pigs_count
            trucks_used_count += 1

            # 1. Càlculs econòmics i de ruta
            dist, final_truck, trip_cost_variable = self.calculate_trip_metrics(route_stops, current_load_kg)
            rev, pen, pen_ratio = self.calculate_economics(route_weights)

            daily_revenue += rev
            daily_transport_cost_var += trip_cost_variable
            
            # 2. LOG TERMINAL - DETALL DE LA RUTA
            route_data = {'route_stops': route_stops, 'current_load_kg': current_load_kg, 'route_pigs_count': route_pigs_count, 
                          'dist': dist, 'final_truck': final_truck, 'trip_cost_variable': trip_cost_variable, 
                          'rev': rev, 'pen': pen, 'pen_ratio': pen_ratio}
            self.print_terminal_log_route(route_data, trucks_used_count)


            # 3. ANIMACIÓ WEB SOCKET
            truck_id = f"TRUCK-{random.randint(1000,9999)}"
            current_loc = self.slaughterhouse_loc
            
            for farm in route_stops:
                await self.animate_travel(websocket, current_loc, farm.loc, truck_id, current_load_kg)
                current_loc = farm.loc
            
            await self.animate_travel(websocket, current_loc, self.slaughterhouse_loc, truck_id, current_load_kg)
            
            # 4. FINALITZACIÓ DEL VIATGE
            await websocket.send_json({
                "type": "TRUCK_ARRIVED",
                "truck_id": truck_id,
                "pigs_delivered": route_pigs_count,
                "total_processed": pigs_processed,
                "metrics_trip": {"revenue": round(rev, 2), "cost": round(trip_cost_variable, 2)}
            })
            await asyncio.sleep(0.5)

        # 5. TANCAMENT DEL DIA I LOGGING AGREGAT
        
        fixed_costs = trucks_used_count * (COST_FIX_CAMIO_SETMANAL / 5) 
        daily_profit = daily_revenue - daily_transport_cost_var - fixed_costs
        
        log_entry = {
            'Dia': day,
            'Porcs Processats': pigs_processed,
            'Camions Usats': trucks_used_count,
            'Ingressos Nets': round(daily_revenue, 2),
            'Costos Var. Transp': round(daily_transport_cost_var, 2),
            'Costos Fixos': round(fixed_costs, 2),
            'Benefici Net Diari': round(daily_profit, 2)
        }
        
        self.daily_logs.append(log_entry)
        
        # 6. LOG TERMINAL - RESUM DIARI I TAULA ACUMULADA
        self.print_terminal_log_summary(log_entry)
        
        # Enviar log agregat a React (per si el frontend vol taula de resultats)
        await websocket.send_json({
            "type": "DAILY_SUMMARY",
            "summary": log_entry,
            "cumulative_profit": round(sum(log['Benefici Net Diari'] for log in self.daily_logs), 2)
        })
        
        return pigs_processed


# --- API CONFIG ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sim_instance = RealTimeSimulation()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    if sim_instance.current_sim_day > DIES_SIMULACIO:
        await websocket.send_json({"type": "SIM_FINISHED", "msg": f"Simulació de {DIES_SIMULACIO} dies finalitzada. Connecti's més tard."})
        await websocket.close()
        return

    try:
        # Executar el dia actual de simulació
        await sim_instance.run_day_stream(websocket, day=sim_instance.current_sim_day)
        
        # Si el dia s'ha executat amb èxit, avancem al següent
        sim_instance.current_sim_day += 1
        await websocket.send_json({"type": "END_OF_SIM", "msg": f"Dia {sim_instance.current_sim_day-1} completat. Proper dia: {sim_instance.current_sim_day}"})

    except Exception as e:
        print(f"ERROR DURANT LA SIMULACIÓ: {e}")
        await websocket.send_json({"type": "ERROR", "msg": str(e)})
    finally:
        await websocket.close()