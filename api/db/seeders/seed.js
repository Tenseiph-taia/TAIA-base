'use strict';
const { execSync } = require('child_process');

console.log('[Seed] Running AgentSeeder...');
execSync('node /app/api/db/seeders/AgentSeeder.js', { stdio: 'inherit' });

console.log('[Seed] Running FileSeeder...');
execSync('node /app/api/db/seeders/FileSeeder.js', { stdio: 'inherit' });

console.log('[Seed] Done.');