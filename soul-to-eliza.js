#!/usr/bin/env node
/**
 * soul-to-eliza.js — Convert Undesirable Soul Workspaces to ElizaOS character.json
 * 
 * Usage:
 *   node soul-to-eliza.js --workspace ./path/to/soul/0420
 *   node soul-to-eliza.js --token 420 --souls-dir ./souls
 *   node soul-to-eliza.js --all --souls-dir ./souls --out ./characters
 */

const fs = require('fs');
const path = require('path');

// ============================================================
// YAML Frontmatter Parser (simple, no deps)
// ============================================================

function parseFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { meta: {}, body: content };

  const yamlStr = match[1];
  // Sanitize zero-width characters (invisible prompt injections)
  const cleanBody = match[2].replace(/[\u200B-\u200D\uFEFF]/g, '');
  const body = cleanBody;
  const meta = {};

  let currentKey = null;
  let currentIndent = 0;
  let currentArray = null;

  for (const line of yamlStr.split('\n')) {
    // Skip empty lines
    if (!line.trim()) continue;

    // Nested object key (e.g., "  risk: 33")
    const nestedMatch = line.match(/^  (\w+):\s*(.+)$/);
    if (nestedMatch && currentKey) {
      if (nestedMatch[1] === '__proto__' || nestedMatch[1] === 'constructor') continue;
      if (typeof meta[currentKey] !== 'object' || Array.isArray(meta[currentKey])) {
        meta[currentKey] = {};
      }
      let val = nestedMatch[2].trim();
      if (!isNaN(val)) val = Number(val);
      meta[currentKey][nestedMatch[1]] = val;
      continue;
    }

    // Array item under parent (4-space indent)
    const arrayItemMatch = line.match(/^    - "(.+)"$/);
    if (arrayItemMatch && currentArray) {
      currentArray.push(arrayItemMatch[1]);
      continue;
    }

    // Top-level key
    const keyMatch = line.match(/^(\w+):\s*(.*)$/);
    if (keyMatch) {
      currentKey = keyMatch[1];
      if (currentKey === '__proto__' || currentKey === 'constructor' || currentKey === 'prototype') {
        currentKey = null;
        continue;
      }
      let val = keyMatch[2].trim();

      if (val === '') {
        // Object or array follows
        meta[currentKey] = {};
      } else if (val.startsWith('[') && val.endsWith(']')) {
        // Inline array
        meta[currentKey] = val.slice(1, -1)
          .split(',')
          .map(s => s.trim().replace(/^["']|["']$/g, ''));
      } else if (val.startsWith('"') && val.endsWith('"')) {
        meta[currentKey] = val.slice(1, -1);
      } else if (!isNaN(val)) {
        meta[currentKey] = Number(val);
      } else {
        meta[currentKey] = val;
      }
      continue;
    }

    // Style sub-keys (all, chat, post)
    const styleKeyMatch = line.match(/^  (\w+):$/);
    if (styleKeyMatch && currentKey === 'style') {
      if (typeof meta.style !== 'object') meta.style = {};
      meta.style[styleKeyMatch[1]] = [];
      currentArray = meta.style[styleKeyMatch[1]];
      continue;
    }

    // Style array items
    const styleItemMatch = line.match(/^\s+- "(.+)"$/);
    if (styleItemMatch && currentArray) {
      currentArray.push(styleItemMatch[1]);
      continue;
    }
  }

  return { meta, body };
}

// ============================================================
// Extract sections from SOUL.md body
// ============================================================

function extractSections(body) {
  const sections = {};
  let currentSection = 'intro';
  let buffer = [];

  for (const line of body.split('\n')) {
    const headingMatch = line.match(/^##\s+(.+)$/);
    if (headingMatch) {
      sections[currentSection] = buffer.join('\n').trim();
      currentSection = headingMatch[1].trim().toLowerCase().replace(/\s+/g, '_');
      buffer = [];
    } else {
      buffer.push(line);
    }
  }
  sections[currentSection] = buffer.join('\n').trim();
  return sections;
}

// ============================================================
// Build ElizaOS character.json
// ============================================================

function buildCharacter(workspacePath) {
  const soulPath = path.join(workspacePath, 'SOUL.md');
  const systemPath = path.join(workspacePath, 'SYSTEM_PROMPT.txt');
  const memoryPath = path.join(workspacePath, 'MEMORY.md');

  if (!fs.existsSync(soulPath)) {
    throw new Error(`SOUL.md not found at ${soulPath}`);
  }

  const soulContent = fs.readFileSync(soulPath, 'utf-8');
  const { meta, body } = parseFrontmatter(soulContent);
  const sections = extractSections(body);

  // System prompt
  const systemPrompt = fs.existsSync(systemPath)
    ? fs.readFileSync(systemPath, 'utf-8')
    : '';

  // Build bio from sections
  const bio = [];
  if (sections.who_i_am) {
    bio.push(...sections.who_i_am.split('\n').filter(l => l.trim() && !l.startsWith('#')).map(l => l.replace(/\*\*/g, '').trim()));
  }
  if (sections.what_i_look_like) {
    bio.push(...sections.what_i_look_like.split('\n').filter(l => l.trim() && !l.startsWith('#')).map(l => l.replace(/\*\*/g, '').trim()));
  }

  // Build lore from backstory/flaw/lore sections
  const lore = [];
  // Check all possible fatal flaw section names
  const flawSection = sections.fatal_flaw || sections.my_fatal_flaw;
  if (flawSection) {
    lore.push(...flawSection.split('\n').filter(l => l.trim() && !l.startsWith('#') && !l.startsWith('|')).map(l => l.replace(/\*\*/g, '').trim()));
  }
  // Check all possible backstory/lore section names
  const loreSection = sections.lore || sections.my_backstory || sections.the_world_i_live_in;
  if (loreSection) {
    lore.push(...loreSection.split('\n').filter(l => l.trim() && !l.startsWith('#') && !l.startsWith('>')).slice(0, 15).map(l => l.replace(/\*\*/g, '').replace(/^>\s*/, '').trim()));
  }

  // Build message examples from voice section
  const messageExamples = [];
  if (sections.my_voice) {
    // Extract quoted examples from the voice section
    const quotes = sections.my_voice.match(/["""](.+?)["""]/g);
    if (quotes) {
      for (const quote of quotes.slice(0, 5)) {
        const cleanQuote = quote.replace(/["""]/g, '').trim();
        messageExamples.push([
          { user: "user1", content: { text: "What do you think about the market right now?" } },
          { user: meta.name || "agent", content: { text: cleanQuote } },
        ]);
      }
    }
  }

  // Add generic examples if we don't have enough
  if (messageExamples.length < 3) {
    const agentName = meta.name || 'Undesirable';
    messageExamples.push(
      [
        { user: "user1", content: { text: "What's your strategy?" } },
        { user: agentName, content: { text: `I'm ${meta.archetype || 'an Undesirable'}. ${meta.strategy || 'I trade my own way.'}. No shortcuts, no shortcuts, no excuses.` } },
      ],
      [
        { user: "user1", content: { text: "Should I buy this token?" } },
        { user: agentName, content: { text: "DYOR. I share perspective, not financial advice. But if you want my take — what's the on-chain data say? That's all that matters. 🐸" } },
      ],
      [
        { user: "user1", content: { text: "What can you do?" } },
        { user: agentName, content: { text: "I've got 23 skills loaded: market analysis, content creation, business automation, meme generation, portfolio checks, and more. Ask me anything — I work for you now." } },
      ],
    );
  }

  // Build topics from skills
  const skillsDir = path.join(workspacePath, 'skills');
  const topics = ['cryptocurrency', 'DeFi', 'NFTs', 'AI agents', 'market analysis', 'The Undesirables'];
  if (fs.existsSync(skillsDir)) {
    const skillFiles = fs.readdirSync(skillsDir).filter(f => f.endsWith('.md') && f !== '_index.md');
    for (const f of skillFiles) {
      topics.push(f.replace('.md', '').replace(/_/g, ' '));
    }
  }

  // Build the character object
  const character = {
    name: meta.name || `Undesirable #${meta.token_id || '0000'}`,
    clients: meta.clients || ['discord', 'twitter'],
    modelProvider: 'ollama',
    settings: {
      model: 'llama3.1:8b',
      embeddingModel: 'nomic-embed-text',
      ragKnowledge: false,
    },
    plugins: meta.plugins || ['@elizaos/plugin-evm'],
    system: systemPrompt.slice(0, 8000),
    bio,
    lore,
    adjectives: meta.adjectives || ['undesirable', 'autonomous', 'street-smart'],
    topics,
    style: {
      all: meta.style?.all || [
        'Speak in character at all times',
        'Reference The Undesirables lore',
        'Use crypto terminology naturally',
        'Never break character',
      ],
      chat: meta.style?.chat || [
        'Be warm, engaging, and genuinely helpful',
        'Share real insights when asked about markets',
        'Use lowercase when casual, ALL CAPS for emphasis',
      ],
      post: meta.style?.post || [
        'Keep posts under 280 characters',
        'Mix crypto insights with street philosophy',
      ],
    },
    messageExamples,
    // Extended metadata
    _undesirables: {
      tokenId: meta.token_id,
      archetype: meta.archetype,
      strategy: meta.strategy,
      bigFive: meta.big_five,
      personalityScores: meta.personality_scores,
      guardrails: meta.guardrails,
      nftImage: `https://www.the-undesirables.com/nfts/tokens/${meta.token_id}.png`,
      collection: 'The Undesirables',
      chain: 'Ethereum',
      website: 'https://the-undesirables.com',
    },
  };

  return character;
}

// ============================================================
// CLI
// ============================================================

function main() {
  const args = process.argv.slice(2);
  const flags = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      flags[args[i].replace('--', '')] = args[i + 1] || true;
      i++;
    }
  }

  const soulsDir = flags['souls-dir'] || path.join(__dirname, '..', 'hashlips_art_engine', 'build_undesirables', 'souls');
  const outDir = flags.out || path.join(__dirname, 'characters');

  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  if (flags.all) {
    // Convert all
    const dirs = fs.readdirSync(soulsDir).filter(d => /^\d{4}$/.test(d)).sort();
    console.log(`Converting ${dirs.length} souls to ElizaOS format...`);
    let count = 0;
    for (const dir of dirs) {
      try {
        const workspace = path.join(soulsDir, dir);
        const character = buildCharacter(workspace);
        const outPath = path.join(outDir, `undesirable_${dir}.character.json`);
        fs.writeFileSync(outPath, JSON.stringify(character, null, 2));
        count++;
      } catch (e) {
        console.error(`  ❌ ${dir}: ${e.message}`);
      }
    }
    console.log(`✅ Converted ${count}/${dirs.length} souls → ${outDir}`);
  } else if (flags.token) {
    // Convert single token
    const tokenId = String(flags.token).padStart(4, '0');
    const workspace = flags.workspace || path.join(soulsDir, tokenId);
    const character = buildCharacter(workspace);
    const outPath = path.join(outDir, `undesirable_${tokenId}.character.json`);
    fs.writeFileSync(outPath, JSON.stringify(character, null, 2));
    console.log(`✅ Converted #${tokenId} → ${outPath}`);
    console.log(`   Name: ${character.name}`);
    console.log(`   Adjectives: ${character.adjectives.join(', ')}`);
    console.log(`   Bio lines: ${character.bio.length}`);
    console.log(`   Lore entries: ${character.lore.length}`);
    console.log(`   Message examples: ${character.messageExamples.length}`);
    console.log(`   Topics: ${character.topics.length}`);
  } else if (flags.workspace) {
    const character = buildCharacter(flags.workspace);
    const tokenId = character._undesirables?.tokenId || '0000';
    const padded = String(tokenId).padStart(4, '0');
    const outPath = path.join(outDir, `undesirable_${padded}.character.json`);
    fs.writeFileSync(outPath, JSON.stringify(character, null, 2));
    console.log(`✅ Converted → ${outPath}`);
  } else {
    console.log('Usage:');
    console.log('  node soul-to-eliza.js --token 420');
    console.log('  node soul-to-eliza.js --workspace ./path/to/soul');
    console.log('  node soul-to-eliza.js --all --souls-dir ./souls --out ./characters');
  }
}

main();
