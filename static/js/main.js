function router() {
    // 1. Get the current hash from the URL (default to #home)
    const currentHash = window.location.hash || '#home';
            
    // 2. Hide all views by removing active styles and ensuring base class is present
    document.querySelectorAll('.view').forEach(view => {
        view.className = 'view'; 
    });
            
    // 3. Find the target div matching the hash ID
    const activeTarget = document.querySelector(currentHash);
            
    // 4. Reveal the target div if it exists
    if (activeTarget) {
        activeTarget.className = 'view active-view';
    } else {
        // Optional: Fallback to home if someone enters an invalid hash
        const homeTarget = document.getElementById('home');
        if (homeTarget) homeTarget.className = 'view active-view';
        }
    
    document.querySelectorAll('nav ul li a').forEach(link => {
    // Get the link's href attribute value (e.g., "#home" or "http://.../#home")
    // Using .getAttribute('href') reads the literal text rather than the resolved full URL
    const linkTarget = link.getAttribute('href');
                
    if (linkTarget === currentHash) {
        link.classList.add('current');
        console.log(linkTarget)
    } else {
        link.classList.remove('current');
    }
    });
}

// Listen for URL changes and initial page load
window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', router);

// ============================================================
// app.js — Solar Irradiance Chart (Today / Tomorrow toggle)
// ============================================================

// ---- 0. Config ----
const LATITUDE = 14;   // TODO: replace with actual user/site coordinates
const LONGITUDE = 121;

// ---- 1. Chart.js setup ----
const ctx = document.getElementById('irradianceChart').getContext('2d');

const chart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [{
      label: 'Solar Irradiance (W/m²)',
      data: [],
      borderColor: '#f5b942',
      backgroundColor: 'rgba(245, 185, 66, 0.2)',
      fill: true,
      tension: 0.4,
      pointRadius: 2,
    }]
  },
  options: {
    responsive: true,
    scales: {
      y: { beginAtZero: true, title: { display: true, text: 'W/m²' } },
      x: { title: { display: true, text: 'Hour' } }
    }
  }
});

// ---- 2. Helpers ----

// hour looks like "2026-08-26T00:00" -- native Date parses this fine
function formatHour(hour) {
  return new Date(hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

function sortReadings(readings) {
  return [...readings].sort((a, b) => new Date(a.hour) - new Date(b.hour));
}

// ---- 3. Fetch + transform ----
async function fetchIrradiance(day) {
  const url = `http://127.0.0.1:8000/api/${day}?latitude=${LATITUDE}&longitude=${LONGITUDE}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const data = await res.json();
  console.log(data);
  // data = { latitude, longitude, day, readings: [{ hour, predicted_irradiance }] }

  const readings = sortReadings(data.readings);

  const hours = readings.map(r => formatHour(r.hour));
  const values = readings.map(r => r.predicted_irradiance);

  return { hours, values };
}

// ---- 4. Load + cache ----
const cache = {};

async function loadChart(day) {
  const daySelect = document.getElementById('daySelect');
  daySelect.disabled = true;

  try {
    if (!cache[day]) {
      cache[day] = await fetchIrradiance(day);
    }
    const { hours, values } = cache[day];
    chart.data.labels = hours;
    chart.data.datasets[0].data = values;
    chart.update();
  } catch (err) {
    console.error('Failed to load irradiance data:', err);
    // optionally surface an error message in the UI here
  } finally {
    daySelect.disabled = false;
  }
}

// ---- 5. Wire up dropdown + initial load ----
document.getElementById('daySelect').addEventListener('change', (e) => {
  loadChart(e.target.value);
});

loadChart('today');

// ============================================================
// pie.js — Total Energy Consumption (Pie Chart, no datalabels plugin)
// ============================================================

const MOCK_DATA = {
  today: {
    labels: ['High Priority', 'Low Priority'],
    values: [67.7, 32.3],
  },
  tomorrow: {
    labels: ['High Priority', 'Low Priority'],
    values: [45.2, 54.8],
  },
};

const COLORS = ['#f5c563', '#33495e'];

const energy_element = document.getElementById('energyChart').getContext('2d');

const energy_chart = new Chart(energy_element, {
  type: 'pie',
  data: {
    labels: MOCK_DATA.today.labels,
    datasets: [{
      data: MOCK_DATA.today.values,
      backgroundColor: COLORS,
      borderWidth: 0,
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: {
        display: true,
        position: 'right',
        labels: {
          font: { weight: 'bold', size: 13 },
          generateLabels: (chart) => {
            const data = chart.data;
            return data.labels.map((label, i) => {
              const value = data.datasets[0].data[i];
              return {
                text: `${label}: ${value}%`,
                fillStyle: data.datasets[0].backgroundColor[i],
                strokeStyle: data.datasets[0].backgroundColor[i],
                index: i,
              };
            });
          }
        }
      },
      tooltip: {
        callbacks: {
          label: (context) => `${context.label}: ${context.raw}%`
        }
      }
    }
  }
});

function loadEnergyChart(day) {
  const dataset = MOCK_DATA[day];
  energy_chart.data.labels = dataset.labels;
  energy_chart.data.datasets[0].data = dataset.values;
  energy_chart.update();
}

document.getElementById('expensesDaySelect').addEventListener('change', (e) => {
  loadEnergyChart(e.target.value);
});