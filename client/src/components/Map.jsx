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

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19
  }).addTo(map);

  const testTruck = L.marker([41.71, 0.64], { icon: transport }).addTo(map);
testTruck.bindPopup("Camión de prueba");

  // ubicacions granges
    farms.forEach(farm => {

        const prob = normalCDF(115, farm.mean_weight_kg, farm.std_weight_kg) - normalCDF(105, farm.mean_weight_kg, farm.std_weight_kg)

        const ready_pigs = Math.round(farm.total_pigs * prob)

      const marker = L.marker([farm.lat, farm.lon]).addTo(map)
      const popup = L.popup({ closeOnClick: false, autoClose: false }).setContent(
    `${farm.name} - ${farm.total_pigs} pigs.
    <br> pigs ready to be sent: ${ready_pigs}`);

  // Show popup on mouseover
  marker.on("mouseover", () => {
    marker.bindPopup(popup).openPopup();
  });

  // Hide popup on mouseout
  marker.on("mouseout", () => {
    marker.closePopup();
  });
    });

      // ubicacions escorxadors
    slaughterhouses.forEach(slaughterhouses => {

        const capacitat_operacio = 100*(slaughterhouses.target_daily - slaughterhouses.daily_capacity_min)/(slaughterhouses.daily_capacity_max - slaughterhouses.daily_capacity_min)

        let icona;

        if(capacitat_operacio<=50){
            icona = {icon: esc_verd}
        }else if(capacitat_operacio>=90){
            icona = {icon: esc_vermell}
        }else{
            icona = {icon: esc_groc}
        }

      const marker = L.marker([slaughterhouses.lat, slaughterhouses.lon], icona).addTo(map)
      const popup = L.popup({ closeOnClick: false, autoClose: false }).setContent(
    `${slaughterhouses.name} - ${slaughterhouses.target_daily} pigs 
    <br> current_capacity: ${capacitat_operacio}%`);

  // Show popup on mouseover
  marker.on("mouseover", () => {
    marker.bindPopup(popup).openPopup();
  });

  // Hide popup on mouseout
  marker.on("mouseout", () => {
    marker.closePopup();
  });
    });
  // Guarda el mapa perquè altres efectes el puguin usar
  mapRef.current._leaflet_map = map;
}, []);


useEffect(() => {
  const map = mapRef.current?._leaflet_map;
  if (!map) return;   // si el mapa no existeix, no fem res encara

  const ws = new WebSocket("ws://localhost:8000/ws");

  ws.onopen = () => console.log("WS connectat");
  ws.onerror = (err) => console.error("WS error:", err);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "TRUCK_UPDATE") {
    const pos = data.position;

    let marker = trucksRef.current[data.truck_id];

    if (marker) {
      // Actualizar posición
      marker.setLatLng(pos);

      // Actualizar popup si ya existe
      if (marker.getPopup()) {
        marker.setPopupContent(`${data.truck_id} - ${data.pigs_on_board} pigs`);
      }
    } else {
      // Crear marcador si no existe
      marker = L.marker(pos, { icon: transport }).addTo(map);
      marker.bindPopup(`${data.truck_id} - ${data.pigs_on_board} pigs`, {
        closeOnClick: false,
        autoClose: false
      });

      // Popups en hover
      marker.on("mouseover", () => marker.openPopup());
      marker.on("mouseout", () => marker.closePopup());

      // Guardamos el marcador
      trucksRef.current[data.truck_id] = marker;
    }
  }
};

  return () => ws.close();
}, []);

  return <div ref={mapRef} className="w-full h-full" />; // attach ref here
}
