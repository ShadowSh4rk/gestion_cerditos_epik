import { useEffect, useRef } from "react";
import L, { popup } from "leaflet";
import farms from "../../../Dades/farms 1.json";
import slaughterhouses from "../../../Dades/slaughterhouses 1.json"
import green_sh from "../assets/granja_verd.png"
import yellow_sh from "../assets/granja_groc.png"
import red_sh from "../assets/granja_vermell.png"
import truck from "../assets/camio.png"

export default function Map() {
  const mapRef = useRef(null); // Ref to the div

  const trucksRef = useRef({}); 
  const slaughterMarkersRef = useRef({}); 
  const farmsMarkersRef = useRef({});
  //funcion de probabilidad

  function normalCDF(x, mean, std) {
  return 0.5 * (1 + erf((x - mean) / (std * Math.sqrt(2))));
}

function erf(x) {
  // aproximación numérica estable
  const sign = (x >= 0) ? 1 : -1;
  x = Math.abs(x);

  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;

  const t = 1 / (1 + p * x);
  const y = 1 - (
    ((
      ((
        ((a5 * t + a4) * t) + a3
      ) * t + a2
      ) * t + a1
    ) * t
    ) * Math.exp(-x * x)
  );

  return sign * y;
}

  //custom icons yayyyyyy
    const esc_verd = L.icon({
  iconUrl: green_sh,
  iconSize: [42, 42],
  iconAnchor: [16, 32],
  popupAnchor: [0, -28],
    });

    const esc_groc = L.icon({
  iconUrl: yellow_sh,
  iconSize: [42, 32],
  iconAnchor: [16, 32],
  popupAnchor: [0, -28],
    });

    const esc_vermell = L.icon({
  iconUrl: red_sh,
  iconSize: [52, 52],
  iconAnchor: [16, 32],
  popupAnchor: [0, -28],
    });

    const transport = L.icon({
  iconUrl: truck,
  iconSize: [52, 52],
  iconAnchor: [16, 32],
  popupAnchor: [0, -28],
    });

useEffect(() => {
  if (!mapRef.current) return;

  const map = L.map(mapRef.current).setView([41.703679, 0.636083], 11);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);

  const testTruck = L.marker([41.71, 0.64], { icon: transport }).addTo(map);
  testTruck.bindPopup("Camión de prueba");

  // === MARCADORES DE GRANJAS ===
  farms.forEach(farm => {
  const prob = normalCDF(115, farm.mean_weight_kg, farm.std_weight_kg) -
               normalCDF(105, farm.mean_weight_kg, farm.std_weight_kg);
  const ready_pigs = Math.round(farm.total_pigs * prob);

  const marker = L.marker([farm.lat, farm.lon]).addTo(map);

  marker.bindPopup(`
    <strong>${farm.name}</strong> <br>
    Total porcs: ${farm.total_pigs} <br>
    Porcs a recollir: ${ready_pigs}
  `);

  marker.on("mouseover", () => marker.openPopup());
  marker.on("mouseout", () => marker.closePopup());

  farmsMarkersRef.current[farm.farm_id] = marker;  // 👈 guardamos la referencia
});

  // === MARCADORES DE ESCORXADORS ===
  slaughterhouses.forEach(sh => {
    const capacitat_operacio = 100 * (sh.target_daily - sh.daily_capacity_min) / (sh.daily_capacity_max - sh.daily_capacity_min);

    let icona;
    if (capacitat_operacio <= 50) icona = esc_verd;
    else if (capacitat_operacio >= 90) icona = esc_vermell;
    else icona = esc_groc;

    const marker = L.marker([sh.lat, sh.lon], { icon: icona }).addTo(map);
    marker.bindPopup(`${sh.name} - ${sh.target_daily} pigs<br>current_capacity: ${capacitat_operacio}%`);

    marker.on("mouseover", () => marker.openPopup());
    marker.on("mouseout", () => marker.closePopup());

    // Guardamos referencia
    slaughterMarkersRef.current[sh.slaughterhouse_id] = marker;
  });

  mapRef.current._leaflet_map = map;
}, []);

// === WEBSOCKET ===
useEffect(() => {
  const map = mapRef.current?._leaflet_map;
  if (!map) return;

  const ws = new WebSocket("ws://localhost:8000/ws");

  ws.onopen = () => console.log("WS connectat");
  ws.onerror = (err) => console.error("WS error:", err);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // === ACTUALIZAR ESCORXADORS ===
    if (data.type === "SLAUGHTERHOUSE_UPDATE") {
  const metrics = data.metrics;

  // usa el id del matadero, que tu backend debería mandar
  const shId = data.slaughterhouse_id || "S1"; // por defecto S1 si solo hay uno
  const marker = slaughterMarkersRef.current[shId];
  if (!marker) return;

  marker.setIcon(
    metrics.capacity_utilization <= 0.5 ? esc_verd :
    metrics.capacity_utilization >= 0.9 ? esc_vermell :
    esc_groc
  );

  marker.setPopupContent(`
    <strong>${slaughterhouses.find(s => s.slaughterhouse_id === shId).name} </strong><br>
    Porcs sacrificats: ${metrics.pigs_delivered} <br>
    Pes viu total: ${metrics.live_weight_total} kg <br>
    Pes canals total: ${metrics.carcass_weight_total} kg <br>
    Pes mitjà viu: ${metrics.avg_live_weight} kg <br>
    Pes mitjà canal: ${metrics.avg_carcass_weight} kg <br>
    Capacitat: ${(metrics.capacity_utilization*100).toFixed(1)}%
  `);
}

   // ------------------ TRUCK ANIMACIÓN ------------------
  if (data.type === "TRUCK_UPDATE") {
    const pos = data.position;
    let marker = trucksRef.current[data.truck_id];

    if (marker) {
      marker.setLatLng(pos);
      if (marker.getPopup()) {
        marker.setPopupContent(`
          ${data.truck_id} <br>
          Porcs a bord: ${data.pigs_on_board} <br>
          Status: ${data.status ?? ""}
        `);
      }
    } else {
      marker = L.marker(pos, { icon: transport }).addTo(map);
      marker.bindPopup(`
        ${data.truck_id} <br>
        Porcs a bord: ${data.pigs_on_board} <br>
        Status: ${data.status ?? ""}
      `, { closeOnClick: false, autoClose: false });
      marker.on("mouseover", () => marker.openPopup());
      marker.on("mouseout", () => marker.closePopup());
      trucksRef.current[data.truck_id] = marker;
    }
  }

  // ------------------ TRUCK MÉTRICAS DIARIAS ------------------
  if (data.type === "TRUCKS_UPDATE") {
    data.trucks.forEach(truck => {
      let marker = trucksRef.current[truck.truck_id];
      if (!marker) {
        // Si no existe, creamos el marcador en la posición del matadero
        marker = L.marker([map.getCenter().lat, map.getCenter().lng], { icon: transport }).addTo(map);
        trucksRef.current[truck.truck_id] = marker;
      }

      // Actualizamos popup
      marker.bindPopup(`
        Nom de viatge: ${truck.truck_id} <br>
        Carrega: ${truck.load_kg} kg <br>
        Porcs: ${truck.num_pigs} <br>
        Pes viu mitjà: ${truck.avg_live_weight} kg <br>
        Granges visitades: ${truck.farms_visited}
      `);
      marker.on("mouseover", () => marker.openPopup());
      marker.on("mouseout", () => marker.closePopup());
    });
  }
    // === ACTUALIZAR GRANGES (opcional) ===
    if (data.type === "FARM_UPDATE") {
  const marker = farmsMarkersRef.current[data.farm_id];
  if (!marker) return;

  marker.bindPopup(`
    <strong>${data.farm_name}</strong> <br>
    Total porcs: ${data.new_inventory + data.num_pigs_loaded} <br>
    Porcs a recollir: ${data.num_pigs_loaded} <br>
    Pes viu mitjà: ${data.avg_weight} kg
  `);

  marker.on("mouseover", () => marker.openPopup());
  marker.on("mouseout", () => marker.closePopup());
}
  };

  return () => ws.close();
}, []);

  return <div ref={mapRef} className="w-full h-full" />; // attach ref here
}