import { useEffect, useState } from "react";

export default function RealtimeMap() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    // Connect to the backend WebSocket
    const ws = new WebSocket("ws://localhost:8000/ws");

    ws.onopen = () => {
      console.log("Connected to WebSocket server");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("Received:", data);

      // Save data to state
      setMessages(prev => [...prev, data]);
    };

    ws.onclose = () => {
      console.log("WebSocket closed");
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };

    // Cleanup on component unmount
    return () => ws.close();
  }, []);

  return (
    <div>
      <h2>Realtime Updates</h2>
      <ul>
        {messages.map((m, i) => (
          <li key={i}>{JSON.stringify(m)}</li>
        ))}
      </ul>
    </div>
  );
}