import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src');

describe('WeatherCard & Overview Weather Integration', () => {
  it('WeatherCard component file exists and defines accessible IDs', () => {
    const cardPath = path.join(root, 'components/weather/WeatherCard.tsx');
    assert.ok(fs.existsSync(cardPath), 'WeatherCard.tsx must exist');
    const content = fs.readFileSync(cardPath, 'utf8');

    assert.ok(content.includes('id="weather-card"'), 'Must define #weather-card');
    assert.ok(content.includes('id="weather-refresh-btn"'), 'Must define #weather-refresh-btn');
    assert.ok(content.includes('id="weather-attribution-link"'), 'Must define #weather-attribution-link');
    assert.ok(content.includes('id="weather-current-temp"'), 'Must define #weather-current-temp');
    assert.ok(content.includes('id="weather-feels-like"'), 'Must define #weather-feels-like');
    assert.ok(content.includes('id="weather-rain-prob"'), 'Must define #weather-rain-prob');
    assert.ok(content.includes('id="weather-wind-speed"'), 'Must define #weather-wind-speed');
    assert.ok(content.includes('id="weather-hourly-section"'), 'Must define #weather-hourly-section');
  });

  it('WeatherCard includes Open-Meteo attribution link and URL', () => {
    const cardPath = path.join(root, 'components/weather/WeatherCard.tsx');
    const content = fs.readFileSync(cardPath, 'utf8');
    assert.ok(
      content.includes('https://open-meteo.com/'),
      'Must link to Open-Meteo URL'
    );
    assert.ok(
      content.includes('Weather data by Open-Meteo.com'),
      'Must include Open-Meteo attribution text'
    );
  });

  it('Weather API client exists and exports fetchCurrentWeather', () => {
    const apiPath = path.join(root, 'api/weather.ts');
    assert.ok(fs.existsSync(apiPath), 'api/weather.ts must exist');
    const content = fs.readFileSync(apiPath, 'utf8');
    assert.ok(content.includes('export async function fetchCurrentWeather'), 'Must export fetchCurrentWeather');
    assert.ok(content.includes('/weather/current'), 'Must call /weather/current endpoint');
  });

  it('OverviewDashboard renders WeatherCard with token prop for authenticated users', () => {
    const dashPath = path.join(root, 'components/dashboard/OverviewDashboard.tsx');
    assert.ok(fs.existsSync(dashPath), 'OverviewDashboard.tsx must exist');
    const content = fs.readFileSync(dashPath, 'utf8');
    assert.ok(content.includes('WeatherCard'), 'OverviewDashboard must import/render WeatherCard');
    assert.ok(content.includes('<WeatherCard token={token}'), 'OverviewDashboard must pass token to WeatherCard');
    assert.ok(content.includes('id="overview-dashboard"'), 'Must define #overview-dashboard');
    assert.ok(content.includes('id="overview-weather-section"'), 'Must define #overview-weather-section');
  });

  it('App.tsx routes overview tab to OverviewDashboard when authenticated and PublicLanding when signed out', () => {
    const appPath = path.join(root, 'App.tsx');
    const content = fs.readFileSync(appPath, 'utf8');
    assert.ok(content.includes('OverviewDashboard'), 'App.tsx must import OverviewDashboard');
    assert.ok(content.includes("activeTab === 'overview'"), 'App.tsx must check overview tab');
    assert.ok(content.includes('<OverviewDashboard'), 'App.tsx must render OverviewDashboard when token is present');
    assert.ok(content.includes('<PublicLanding'), 'App.tsx must render PublicLanding when token is absent');
  });
});
