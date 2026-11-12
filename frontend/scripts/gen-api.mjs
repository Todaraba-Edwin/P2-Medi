// 백엔드 OpenAPI(JSON 사본)에서 TypeScript 타입을 만든다(FE-01-11 A). 서버를 띄우지 않는다.
// 실행: pnpm gen:api [openapi.json 경로]   기본 경로: ../data/mock/openapi-v1.json(로컬 전용 사본)
// 사본 만들기(메인): cd backend && .venv/bin/python scripts/export_openapi.py -o ../data/mock/openapi-v1.json
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const source = path.resolve(process.cwd(), process.argv[2] ?? path.join(frontend, "../data/mock/openapi-v1.json"));
const target = path.join(frontend, "src/lib/api/generated.ts");

const document = JSON.parse(readFileSync(source, "utf8"));
const ast = await openapiTS(document);
const header = `// 생성 파일이다. 손으로 고치지 않는다.
// 원본: 백엔드 OpenAPI(${document.info?.title ?? "API"} ${document.info?.version ?? ""}, backend/scripts/export_openapi.py 결과)
// 다시 만들기: pnpm gen:api
`;
writeFileSync(target, header + astToString(ast));
process.stdout.write(`wrote ${path.relative(frontend, target)}\n`);
