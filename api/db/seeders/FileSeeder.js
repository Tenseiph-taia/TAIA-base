const fs = require('fs');
const path = require('path');
const FormData = require('form-data');
const axios = require('axios');
require('dotenv').config({ path: path.resolve(__dirname, '../../../.env') });
const mongoose = require('mongoose');

const MONGO_URI = process.env.MONGO_URI || 'mongodb://mongodb:27017/LibreChat';
const RAG_API_URL = process.env.RAG_API_URL || 'http://localhost:8000';
const AGENT_ID = 'agent_taia_default';

// ─── AUTO-DISCOVER ALL FILES IN SEEDS FOLDER ──────────────────────────────────
const SEEDS_DIR = path.resolve(__dirname, '../../../docs/seeds');
const FILES_TO_SEED = fs.readdirSync(SEEDS_DIR)
  .filter(f => !f.startsWith('.')) // skip hidden files
  .map(f => path.join(SEEDS_DIR, f));
// ──────────────────────────────────────────────────────────────────────────────

const getMimeType = (filePath) => {
  const ext = path.extname(filePath).toLowerCase();
  const map = {
    '.pdf': 'application/pdf',
    '.md': 'text/markdown',
    '.txt': 'text/plain',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  };
  return map[ext] || 'application/octet-stream';
};

const generateFileId = () => {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
};

const uploadToRagApi = async (filePath, fileId, adminUserId) => {
  const filename = path.basename(filePath);
  const fileBuffer = fs.readFileSync(filePath);
  const mimeType = getMimeType(filePath);

  const form = new FormData();
  form.append('file', fileBuffer, { filename, contentType: mimeType });
  form.append('file_id', fileId);

  console.log(`[FileSeeder] Uploading "${filename}" to rag_api...`);

  const response = await axios.post(`${RAG_API_URL}/embed`, form, {
    headers: {
      ...form.getHeaders(),
      // Generate a simple JWT for rag_api auth
      Authorization: `Bearer ${generateJwt(adminUserId)}`,
    },
    timeout: 60000,
  });

  return response.data;
};

const generateJwt = (userId) => {
  // Use LibreChat's JWT secret to generate a token
  const jwt = require('jsonwebtoken');
  return jwt.sign({ id: userId }, process.env.JWT_SECRET, { expiresIn: '1h' });
};

const run = async () => {
  try {
    await mongoose.connect(MONGO_URI);

    const db = mongoose.connection.db;

    // Get admin user
    const adminUser = await db.collection('users').findOne({ role: 'ADMIN' });
    if (!adminUser) {
      console.error('[FileSeeder] No ADMIN user found.');
      process.exit(1);
    }
    console.log(`[FileSeeder] Using admin: ${adminUser.email}`);

    // Get the agent
    const agent = await db.collection('agents').findOne({ id: AGENT_ID });
    if (!agent) {
      console.error(`[FileSeeder] Agent "${AGENT_ID}" not found. Run AgentSeeder first.`);
      process.exit(1);
    }

    const newFileIds = [];

    for (const filePath of FILES_TO_SEED) {
      if (!fs.existsSync(filePath)) {
        console.warn(`[FileSeeder] File not found, skipping: ${filePath}`);
        continue;
      }

      const filename = path.basename(filePath);
      const fileId = generateFileId();
      const mimeType = getMimeType(filePath);
      const fileStats = fs.statSync(filePath);

      // Check if already registered in MongoDB
      const existingFile = await db.collection('files').findOne({
        filename,
        user: adminUser._id,
      });

      if (existingFile) {
        console.log(`[FileSeeder] "${filename}" already registered — reusing file_id: ${existingFile.file_id}`);
        newFileIds.push(existingFile.file_id);
        continue;
      }

      // Upload to rag_api
      await uploadToRagApi(filePath, fileId, adminUser._id.toString());

      // Register in MongoDB files collection
      const now = new Date();
      await db.collection('files').insertOne({
        file_id: fileId,
        filename,
        originalname: filename,
        type: mimeType,
        size: fileStats.size,
        user: adminUser._id,
        source: 'local',
        embedded: true,
        filepath: `/uploads/${adminUser._id}/${filename}`,
        createdAt: now,
        updatedAt: now,
        __v: 0,
      });

      console.log(`[FileSeeder] ✓ Registered "${filename}" with file_id: ${fileId}`);
      newFileIds.push(fileId);
    }

    if (newFileIds.length === 0) {
      console.log('[FileSeeder] No new files to attach.');
      process.exit(0);
    }

    // Attach file_ids to agent tool_resources.file_search
    const existingFileIds = agent.tool_resources?.file_search?.file_ids ?? [];
    const mergedFileIds = [...new Set([...existingFileIds, ...newFileIds])];

    await db.collection('agents').updateOne(
      { id: AGENT_ID },
      {
        $set: {
          'tool_resources.file_search.file_ids': mergedFileIds,
          tools: [...new Set([...(agent.tools ?? []), 'file_search'])],
          updatedAt: new Date(),
        },
      },
    );

    process.exit(0);
  } catch (error) {
    console.error('[FileSeeder] Error:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
};

run();