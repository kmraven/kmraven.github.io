import { readFile, writeFile, mkdir, rename, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { importResearchmap, ImportError } from '../src/lib/import-researchmap.ts';

const output = fileURLToPath(new URL('../src/data/researchmap.public.json', import.meta.url));
const args = process.argv.slice(2);
if (args.length !== 1 || args[0].startsWith('-')) {
  console.error('Usage: npm run import:researchmap -- <complete-export.jsonl>');
  process.exitCode = 1;
} else {
  const temporary = `${output}.${process.pid}.tmp`;
  try {
    const { data, report } = importResearchmap(await readFile(path.resolve(args[0]), 'utf8'));
    await mkdir(path.dirname(output), { recursive: true });
    await writeFile(temporary, `${JSON.stringify(data, null, 2)}\n`, { flag: 'wx' });
    await rename(temporary, output);
    console.log('公開用データを更新しました。元のエクスポートはコピーしていません。');
    console.log(`採用: ${Object.entries(report.included).map(([type, count]) => `${type}=${count}`).join(', ')}`);
    console.log(`公開対象外: ${report.hidden} 件`);
    if (Object.keys(report.unsupported).length) {
      console.warn(`未対応の種別（未掲載）: ${Object.entries(report.unsupported).map(([type, count]) => `${type}=${count}`).join(', ')}`);
    }
    console.log('git diff -- src/data/researchmap.public.json で公開内容を確認してください。');
  } catch (error) {
    await rm(temporary, { force: true });
    console.error(error instanceof ImportError ? error.message : 'ファイルの読み書きに失敗しました。入力パスと権限を確認してください。');
    process.exitCode = 1;
  }
}
