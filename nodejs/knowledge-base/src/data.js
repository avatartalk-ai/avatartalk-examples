import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { settings } from './config.js';
import { getOpenAI } from './openai_client.js';

export class KnowledgeBase {
  constructor() {
    this.openai = getOpenAI();
    this.vectorStoreId = null;
  }

  async createVectorStore(vectorStoreName) {
    try {
      const vs = await this.openai.vectorStores.create({ name: vectorStoreName });
      const details = {
        id: vs.id,
        name: vs.name,
        created_at: vs.created_at,
        file_count: vs.file_counts?.completed ?? 0,
      };
      // eslint-disable-next-line no-console
      console.log(`Vector store ${vectorStoreName} created:`, details);
      this.vectorStoreId = details.id;
      return details;
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error(`Error creating vector store ${vectorStoreName}:`, e);
      return {};
    }
  }

  async uploadSingleFileToVectorStore(filePath, vectorStoreId) {
    const fileName = path.basename(filePath);
    try {
      const file = await this.openai.files.create({
        file: fs.createReadStream(filePath),
        purpose: 'assistants',
      });
      await this.openai.vectorStores.files.create(vectorStoreId, { file_id: file.id });
      return { file: fileName, status: 'success' };
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error(`Error uploading file ${fileName}:`, e);
      return { file: fileName, status: 'error', error: String(e?.message || e) };
    }
  }

  async uploadDirectoryToVectorStore(directoryPath, vectorStoreId) {
    const absDir = path.resolve(directoryPath);
    let entries = [];
    try {
      entries = await fs.promises.readdir(absDir, { withFileTypes: true });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error(`Error reading directory ${absDir}:`, e);
      return { total_files: 0, successful_uploads: 0, failed_uploads: 0, errors: [] };
    }

    const files = entries
      .filter((d) => d.isFile())
      .map((d) => path.join(absDir, d.name));

    const stats = {
      total_files: files.length,
      successful_uploads: 0,
      failed_uploads: 0,
      errors: [],
    };

    // eslint-disable-next-line no-console
    console.log(`Uploading ${stats.total_files} files to vector store ${vectorStoreId}...`);

    // Simple concurrency limiter (up to CPU count - 1, at least 2)
    const maxWorkers = Math.max(2, (os.cpus()?.length || 2) - 1);
    let idx = 0;
    const runNext = async () => {
      if (idx >= files.length) return;
      const filePath = files[idx++];
      const result = await this.uploadSingleFileToVectorStore(filePath, vectorStoreId);
      if (result.status === 'success') {
        stats.successful_uploads += 1;
        // eslint-disable-next-line no-console
        console.log(`Uploaded file ${result.file}`);
      } else {
        stats.failed_uploads += 1;
        stats.errors.push(result);
      }
      await runNext();
    };
    await Promise.all(Array.from({ length: Math.min(maxWorkers, files.length) }, () => runNext()));

    return stats;
  }

  async createAndInitializeVectorStore(vectorStoreName, directoryPath) {
    const vs = await this.createVectorStore(vectorStoreName);
    if (!vs || !vs.id) {
      throw new Error('Failed to create vector store');
    }
    const stats = await this.uploadDirectoryToVectorStore(directoryPath, vs.id);
    return stats;
  }

  async shutDownVectorStore() {
    if (this.vectorStoreId) {
      try {
        await this.openai.vectorStores.del(this.vectorStoreId);
        // eslint-disable-next-line no-console
        console.log(`Vector store ${this.vectorStoreId} deleted successfully`);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error(`Error deleting vector store ${this.vectorStoreId}:`, e);
      }
    } else {
      // eslint-disable-next-line no-console
      console.log('No vector store ID found');
    }
  }
}

export async function buildKnowledgeBase() {
  const kb = new KnowledgeBase();
  await kb.createAndInitializeVectorStore(
    settings.vector_store_name,
    settings.knowledge_base_directory_path,
  );
  return kb;
}

