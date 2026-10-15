function connect() {
      // Use wss:// automatically when the page is served over https
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${protocol}://${location.host}/ws`);

      socket.onopen = () => {
        document.getElementById("status").textContent = "connected";
      };

      socket.onmessage = (event) => {
        // event.data is the string the server sent via broadcast()
        const data = JSON.parse(event.data);
        document.getElementById("battery-percentage").textContent = data.cpu.toFixed(1) + "%";
        document.getElementById("solar-consumption").textContent = data.memory.toFixed(1) + "kW";
      };

      socket.onclose = () => {
        document.getElementById("status").textContent = "disconnected, retrying...";
        setTimeout(connect, 2000); // simple auto-reconnect
      };

      socket.onerror = () => socket.close();
    }

connect();