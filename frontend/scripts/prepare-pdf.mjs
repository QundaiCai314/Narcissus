import { cp, mkdir } from "node:fs/promises";
await mkdir("public/pdfjs", { recursive: true });
await cp("node_modules/pdfjs-dist/LICENSE", "public/pdfjs/LICENSE");
await cp(
  "node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
  "public/pdfjs/pdf.worker.min.mjs",
);
for (const directory of ["cmaps", "standard_fonts", "wasm"]) {
  await cp(
    `node_modules/pdfjs-dist/${directory}`,
    `public/pdfjs/${directory}`,
    { recursive: true },
  );
}
