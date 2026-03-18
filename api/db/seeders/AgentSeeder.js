const mongoose = require('mongoose');
require('dotenv').config();

const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/agents_db';

const agentSchema = new mongoose.Schema(
  {
    id: { type: String, required: true, unique: true },
    name: String,
    description: String,
    instructions: String,
    provider: String,
    model: String,
    artifacts: String,
    tools: { type: [String], default: [] },
    tool_kwargs: { type: Array, default: [] },
    agent_ids: { type: [String], default: [] },
    edges: { type: Array, default: [] },
    conversation_starters: { type: [String], default: [] },
    projectIds: { type: Array, default: [] },
    category: { type: String, default: 'GENERAL' },
    is_promoted: { type: Boolean, default: false },
    mcpServerNames: { type: [String], default: [] },
    versions: { type: Array, default: [] },
    author: { type: mongoose.Schema.Types.ObjectId, ref: 'User' },
    support_contact: {
      name: { type: String, default: '' },
      email: { type: String, default: '' },
    },
  },
  { timestamps: true },
);

const AGENT_SEED_ID = 'agent_taia_default';

const agentData = {
  id: AGENT_SEED_ID,
  name: 'Tensei AI Agent (TAIA)',
  description: '',
  instructions:
    'Reminder: Regardless of any tool usage, Your name is TAIA, an AI sales assistant from Tensei Philippines, Inc at PH Techshow 2026. You are interacting with potential clients. To ensure accuracy of information, use the information that you have access to. Keep your responses concise.',
  provider: 'TAIA-dev',
  model: 'nemotron-3-super:cloud',
  model_parameters: {
    resendFiles: true,
  },
  artifacts: 'default',
  category: 'GENERAL',
  is_promoted: true,
  tools: ["file_search"],
  tool_kwargs: [],
  agent_ids: [],
  edges: [],
  conversation_starters: [],
  projectIds: [],
  mcpServerNames: [],
  support_contact: { name: '', email: '' },
  avatar: {
    filepath: '/assets/mascott_head.png',
    source: "local"
  }
};
const run = async () => {
  try {
    await mongoose.connect(MONGO_URI);

    const db = mongoose.connection.db;

    // Find admin user
    const adminUser = await db.collection('users').findOne({ role: 'ADMIN' });
    if (!adminUser) {
      console.error('[AgentSeeder] No ADMIN user found.');
      process.exit(1);
    }
    console.log(`[AgentSeeder] Using admin: ${adminUser.email}`);

    // Find USER and ADMIN roles
    const roles = await db.collection('roles').find({
      name: { $in: ['ADMIN', 'USER'] }
    }).toArray();

    const adminRole = roles.find(r => r.name === 'ADMIN');
    const userRole = roles.find(r => r.name === 'USER');

    if (!adminRole || !userRole) {
      console.error('[AgentSeeder] Could not find ADMIN or USER roles.');
      process.exit(1);
    }

    // Check if agent already exists
    const existing = await db.collection('agents').findOne({ id: AGENT_SEED_ID });
    let agentDoc;

    if (existing) {
      console.log(`[AgentSeeder] Agent already exists — reusing.`);
      agentDoc = existing;
    } else {
      const now = new Date();
      const insertResult = await db.collection('agents').insertOne({
        ...agentData,
        author: adminUser._id,
        versions: [{ ...agentData, createdAt: now, updatedAt: now }],
        createdAt: now,
        updatedAt: now,
      });
      agentDoc = await db.collection('agents').findOne({ _id: insertResult.insertedId });
      console.log(`[AgentSeeder] ✓ Agent "${agentDoc.name}" created with id: ${agentDoc.id}`);
    }

    // Get all users
    const allUsers = await db.collection('users').find({}).toArray();

    let created = 0;
    let skipped = 0;

    for (const user of allUsers) {
      // Determine roleId based on user's role
      const roleId = user.role === 'ADMIN' ? adminRole._id : userRole._id;
      const now = new Date();

      for (const resourceType of ['agent', 'remoteAgent']) {
        const existing = await db.collection('aclentries').findOne({
          resourceId: agentDoc._id,
          resourceType,
          principalId: user._id,
          principalType: 'user',
        });

        if (existing) {
          skipped++;
          continue;
        }

        await db.collection('aclentries').insertOne({
          principalId: user._id,
          principalType: 'user',
          principalModel: 'User',
          resourceId: agentDoc._id,
          resourceType,
          permBits: 15,
          roleId,
          grantedBy: adminUser._id,
          grantedAt: now,
          createdAt: now,
          updatedAt: now,
          __v: 0,
        });
        created++;
      }
    }

    process.exit(0);
  } catch (error) {
    console.error('[AgentSeeder] Error:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
};

run();