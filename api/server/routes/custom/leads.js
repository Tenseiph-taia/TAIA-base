const express = require('express');
const fs = require('fs');
const path = require('path');
const { logger } = require('@librechat/data-schemas');

const router = express.Router();
const LEADS_FILE = path.resolve('/app/leads/leads.csv');

const ensureLeadsDir = () => {
  const dir = path.dirname(LEADS_FILE);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  if (!fs.existsSync(LEADS_FILE)) {
    fs.writeFileSync(LEADS_FILE, 'timestamp,name,company,email,phone,industry,facilities,notes\n');
  }
};

router.post('/', async (req, res) => {
  try {
    ensureLeadsDir();
    const {
      name = '',
      company = '',
      email = '',
      phone = '',
      industry = '',
      facilities = '',
      notes = '',
    } = req.body;

    const timestamp = new Date().toISOString();
    const row = [timestamp, name, company, email, phone, industry, facilities, notes]
      .map(v => `"${String(v).replace(/"/g, '""')}"`)
      .join(',');

    // Read existing content
    const content = fs.readFileSync(LEADS_FILE, 'utf8');
    const lines = content.split('\n').filter(Boolean);

    // Check if lead already exists by name + company
    const existingIndex = lines.findIndex((line, i) => {
      if (i === 0) return false; // skip header
      return line.includes(`"${name}"`) && line.includes(`"${company}"`);
    });

    if (existingIndex > -1) {
      // Update existing row
      lines[existingIndex] = row;
      fs.writeFileSync(LEADS_FILE, lines.join('\n') + '\n');
      logger.info(`[LeadsRoute] Lead updated: ${name} from ${company}`);
    } else {
      // Append new row
      fs.appendFileSync(LEADS_FILE, row + '\n');
      logger.info(`[LeadsRoute] Lead saved: ${name} from ${company}`);
    }

    res.status(200).json({ success: true, message: 'Lead saved successfully' });
  } catch (error) {
    logger.error('[LeadsRoute] Error saving lead:', error);
    res.status(500).json({ success: false, message: 'Failed to save lead' });
  }
});

router.get('/', async (req, res) => {
  try {
    ensureLeadsDir();
    const content = fs.readFileSync(LEADS_FILE, 'utf8');
    res.status(200).send(content);
  } catch (error) {
    res.status(500).json({ success: false, message: 'Failed to read leads' });
  }
});

module.exports = router;