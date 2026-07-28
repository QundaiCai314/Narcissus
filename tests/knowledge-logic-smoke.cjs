const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");

const appPath = path.join(__dirname, "..", "app.js");
const source = fs.readFileSync(appPath, "utf8").replace(/\nnavButtons\.forEach\(\(button\) => button\.addEventListener[\s\S]*$/, "");
const storage = new Map();
const context = {
  console,
  structuredClone,
  crypto: webcrypto,
  URL,
  setTimeout,
  clearTimeout,
  localStorage: {
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key)
  },
  document: {
    baseURI: "http://localhost/",
    body: { dataset: {} },
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => []
  },
  window: { setTimeout, clearTimeout, addEventListener: () => {}, pdfjsLib: null, mammoth: null, MathJax: null }
};
context.window.window = context.window;
vm.createContext(context);
vm.runInContext(source, context, { filename: appPath });

const chunks = [
  { id: "a", fileName: "课程.pdf", fileId: "f1", page: 10, paragraph: 1, structuralChapter: "第1章 · 哈希函数", text: "哈希函数将任意长度的消息映射为固定长度的散列值，并应满足单向性。" },
  { id: "b", fileName: "课程.pdf", fileId: "f1", page: 2, paragraph: 1, structuralChapter: "课程.pdf · 导言", text: "版权所有，出版社出版，ISBN 978-7-0000-0000-0。" },
  { id: "c", fileName: "课程.pdf", fileId: "f1", page: 11, paragraph: 1, structuralChapter: "第1章 · 哈希函数", text: "消息认证码用于验证消息完整性和消息来源，需要通信双方共享密钥。" }
];
const parsed = {
  chapters: [{
    title: "第1章 · 哈希函数",
    knowledgePoints: [
      { parentKnowledgePoint: "哈希函数原理", name: "哈希函数的映射特性", chunkIds: ["C1"], evidence: [{ chunkId: "C1", quote: "哈希函数将任意长度的消息映射为固定长度的散列值" }] },
      { parentKnowledgePoint: "量子密码", name: "量子密钥分发", chunkIds: ["C3"], evidence: [{ chunkId: "C3", quote: "消息认证码用于验证消息完整性" }] }
    ]
  }],
  excludedChunks: [{ chunkId: "C2", reason: "版权与出版信息" }]
};

const audit = context.auditOutlineBatchResult(parsed, chunks, { structureMode: "chapter" });
assert.equal(audit.parsed.chapters.length, 1);
assert.equal(audit.parsed.chapters[0].knowledgePoints.length, 1);
assert.equal(audit.parsed.chapters[0].knowledgePoints[0].name, "哈希函数的映射特性");
assert.equal(audit.invalidCount, 1);
assert.deepEqual(Array.from(audit.missingIds), ["C3"]);
assert.deepEqual(Array.from(audit.excludedIds), ["C2"]);
assert.equal(context.areSimilarKnowledgePoints("哈希函数", "哈希函数安全性"), false);
assert.equal(context.areSimilarKnowledgePoints("哈希函数", "哈希函数基本概念"), true);

const batches = context.buildKnowledgeAnalysisBatches([
  ...Array.from({ length: 15 }, (_, index) => ({ ...chunks[0], id: `a${index}`, paragraph: index + 1 })),
  ...Array.from({ length: 3 }, (_, index) => ({ ...chunks[2], id: `c${index}`, structuralChapter: "第2章 · 消息认证", paragraph: index + 1 }))
], "chapter");
assert.ok(batches.length >= 3);
assert.ok(batches.every((batch) => batch.length <= 8));
assert.ok(batches.every((batch) => new Set(batch.map((chunk) => chunk.structuralChapter)).size === 1));

const evidenceChunks = Array.from({ length: 4 }, (_, index) => ({
  ...chunks[0],
  id: `e${index}`,
  paragraph: index + 1,
  text: `哈希函数映射特性说明${"用于验证每个片段必须拥有独立原文证据。".repeat(28)}`
}));
const incompleteEvidence = context.auditOutlineBatchResult({
  chapters: [{
    title: "第1章 · 哈希函数",
    knowledgePoints: [{
      parentKnowledgePoint: "哈希函数原理",
      name: "哈希函数映射特性",
      chunkIds: ["C1", "C2", "C3", "C4"],
      evidence: [{ chunkId: "C1", quote: "哈希函数映射特性说明用于验证每个片段必须拥有独立原文证据" }]
    }]
  }]
}, evidenceChunks, { structureMode: "chapter" });
assert.deepEqual(Array.from(incompleteEvidence.missingIds), ["C2", "C3", "C4"]);

const fullyEvidenced = context.auditOutlineBatchResult({
  chapters: [{
    title: "第1章 · 哈希函数",
    knowledgePoints: [{
      parentKnowledgePoint: "哈希函数原理",
      name: "哈希函数映射特性",
      chunkIds: ["C1", "C2", "C3", "C4"],
      evidence: ["C1", "C2", "C3", "C4"].map((chunkId) => ({ chunkId, quote: "哈希函数映射特性说明用于验证每个片段必须拥有独立原文证据" }))
    }]
  }]
}, evidenceChunks, { structureMode: "chapter" });
assert.equal(fullyEvidenced.undersegmented, true);

const longChunk = { ...chunks[0], id: "long", text: "哈希函数用于构造消息摘要并支持完整性验证。".repeat(120) };
const granularCourse = { files: [{ id: "f1", chunkCount: 1 }], chunks: [longChunk] };
const granular = context.ensureKnowledgeAnalysisGranularity(granularCourse, [longChunk]);
assert.ok(granular.length >= 3);
assert.ok(granular.every((chunk) => chunk.text.length <= 1080));
assert.equal(granularCourse.chunks.length, granular.length);

const directoryCourse = {
  name: "密码学",
  files: [{ id: "f1", name: "课程.pdf" }],
  directoryOutline: { f1: { "chapter:1": "第1章 · 哈希函数", "chapter:2": "第2章 · 消息认证" } },
  subjectSelection: {},
  subjectAnalysis: { name: "密码学" }
};
const directoryReference = context.buildDirectoryKnowledgeReference(directoryCourse, [chunks[0]]);
assert.ok(directoryReference.includes("第1章 · 哈希函数"));
assert.ok(directoryReference.includes("第2章 · 消息认证"));
const directoryPrompt = context.buildOutlineBatchPrompt(directoryCourse, [chunks[0]], { structureMode: "chapter" });
assert.ok(directoryPrompt.some((message) => message.content.includes("目录是章节边界和总分结构的主要参考标准之一")));

const chapterNameCourse = {
  directoryOutline: {
    f1: {
      "chapter:1": "第1章 · 哈希函数",
      "chapter:13": "第13章",
      "chapter:14": "第14章 · 网络环境下身份认证体系的设计原则以及工程实践中的安全边界"
    }
  },
  chapterDisplayNames: {},
  subjectAnalysis: { domain: "general" },
  chunks: [
    { structuralChapter: "第1章 · 哈希函数", text: "哈希函数基础。" },
    { structuralChapter: "第13章", knowledgeParent: "防火墙技术", knowledgePoint: "包过滤防火墙", text: "防火墙通过安全策略控制网络访问。" },
    { structuralChapter: "第14章 · 网络环境下身份认证体系的设计原则以及工程实践中的安全边界", knowledgeParent: "身份认证机制", knowledgePoint: "身份认证协议", text: "身份认证机制用于确认通信实体身份。" }
  ]
};
const displayNames = context.refreshChapterDisplayNames(chapterNameCourse);
assert.equal(displayNames["第1章 · 哈希函数"], "第1章 · 哈希函数");
assert.equal(displayNames["第13章"], "第13章 · 防火墙技术");
assert.ok(displayNames["第14章 · 网络环境下身份认证体系的设计原则以及工程实践中的安全边界"].startsWith("第14章 · 身份认证"));
assert.ok(displayNames["第14章 · 网络环境下身份认证体系的设计原则以及工程实践中的安全边界"].length <= 26);

assert.equal(context.getGenerationBatchSize({ scope: "reader_pages", typeMode: "mixed" }), 2);
assert.equal(context.getGenerationBatchSize({ scope: "reader_pages", typeMode: "subjective" }), 1);
assert.equal(context.getGenerationBatchSize({ scope: "reader_pages", typeMode: "mixed", modelName: "LongCat-2.0" }), 2);
assert.equal(context.getGenerationBatchSize({ scope: "knowledge", typeMode: "mixed" }), 4);
assert.equal(context.getGenerationBatchSizeForSlot({ scope: "reader_pages" }, { type: "single" }, 2), 2);
assert.equal(context.getGenerationBatchSizeForSlot({ scope: "reader_pages" }, { type: "blank" }, 2), 1);
assert.equal(context.getGenerationBatchSizeForSlot({ scope: "reader_pages" }, { type: "essay" }, 2), 1);
assert.equal(context.getGenerationBatchSizeForSlot({ scope: "knowledge" }, { type: "essay" }, 4), 4);
assert.equal(context.getGenerationRequestTimeoutMs({ scope: "reader_pages" }), 180000);
assert.equal(context.getGenerationTokenBudget({ scope: "reader_pages", blueprint: [{ type: "single" }] }), 1450);
assert.equal(context.getGenerationTokenBudget({ scope: "reader_pages", blueprint: [{ type: "single" }, { type: "multiple" }] }), 2450);
assert.equal(context.getGenerationTokenBudget({ scope: "reader_pages", blueprint: [{ type: "essay" }] }), 3800);
assert.equal(context.getGroundingAuditTokenBudget(1), 500);
assert.equal(context.getGroundingAuditTokenBudget(2), 640);
assert.equal(context.shouldRunAiGroundingAudit({ fastMode: false }), true);
assert.equal(context.shouldRunAiGroundingAudit({ fastMode: true }), false);
assert.equal(context.normalizeQuestionType("选择题", { options: ["A", "B", "C", "D"], answer: "C" }), "single");
assert.equal(context.normalizeQuestionType("选择题", { options: ["A", "B", "C", "D"], answer: "A,C" }), "multiple");
assert.equal(context.normalizeQuestionType("single", { stem: "数据加密标准（DES）的分组长度是（ ）？", options: ["A. 32", "B. 64", "C. 128", "D. 256"], answer: "B" }), "single");
assert.equal(context.normalizeQuestionType("", { stem: "数据加密标准的分组长度是（ ）。", options: [], answer: "64 位" }), "blank");
assert.equal(context.areQuestionTypesCompatible("multiple", "single"), true);
assert.equal(context.areQuestionTypesCompatible("blank", "multiple"), false);
const fastChunkMap = new Map([["S1", { text: "高级加密标准采用替代和置换等步骤。" }]]);
const fastBlank = { type: "blank", stem: "高级加密标准的英文缩写为（ ）。", options: [], answer: "AES", explanation: "AES 是高级加密标准的英文缩写，用于标识该分组密码标准。", sourceIds: ["S1"] };
assert.equal(context.validateGeneratedQuestionForMode(fastBlank, { type: "blank", allowedSourceIds: ["S1"] }, fastChunkMap, { fastMode: true }).ok, true);
assert.equal(context.validateGeneratedQuestionForMode(fastBlank, { type: "blank", allowedSourceIds: ["S1"] }, fastChunkMap, { fastMode: false }).ok, false);
const fastShort = { type: "short", stem: "简述高级加密标准轮函数的主要作用及其结构特点。", options: [], answer: "高级加密标准的轮函数通过字节替代、行移位、列混合和轮密钥加等步骤反复变换数据，使明文与密钥之间形成复杂关系。各步骤承担不同的混淆与扩散作用，最后一轮省略列混合，以便保持可逆结构并完成加密。", explanation: "回答需要同时说明轮函数的步骤、混淆扩散作用以及最后一轮的结构差异。", sourceIds: ["S1"] };
const fastEssay = { type: "essay", stem: "论述高级加密标准的轮结构如何实现安全性与可逆性。", options: [], answer: "高级加密标准采用多轮迭代结构处理固定长度的数据分组。字节替代提供非线性变换，降低输入与输出之间的简单对应关系；行移位改变字节位置，使不同列的数据发生联系；列混合进一步扩大单个输入变化对输出的影响；轮密钥加把扩展后的密钥材料引入每一轮。解密时，各步骤按照相反顺序执行对应逆变换，并逆序使用扩展密钥，因此能够恢复原始数据。最后一轮省略列混合，是算法既定结构的一部分，并不改变其可逆性。理解这一结构时，应把安全性建立在多轮非线性、位置变换、扩散与密钥混合的共同作用上，而不能把安全性归因于某一个孤立步骤。答题时还应区分加密步骤与解密步骤的顺序关系，说明逆变换和逆序轮密钥如何共同保证正确解密。", explanation: "论述题应围绕轮结构、各步骤作用、解密逆过程和整体安全机制分层展开。", sourceIds: ["S1"] };
assert.equal(context.validateGeneratedQuestionForMode(fastShort, { type: "short", allowedSourceIds: ["S1"] }, fastChunkMap, { fastMode: true }).ok, true);
assert.equal(context.validateGeneratedQuestionForMode(fastEssay, { type: "essay", allowedSourceIds: ["S1"] }, fastChunkMap, { fastMode: true }).ok, true);
assert.equal(context.getAiTeacherResponseText({ choices: [{ message: { content: "知识点讲解" } }] }), "知识点讲解");
assert.equal(context.getAiTeacherResponseText({ choices: [{ message: { content: [{ text: "第一部分" }, { text: "第二部分" }] } }] }), "第一部分\n第二部分");
const wrongTeacherCard = context.renderGradingCard({ correct: false, score: 0, feedback: "需要订正" }, { id: "q1", type: "single", stem: "题干", answer: "A", explanation: "解析" }, { mistakeBook: [], excellentBook: [] });
const correctTeacherCard = context.renderGradingCard({ correct: true, score: 100, feedback: "回答正确" }, { id: "q1", type: "single", stem: "题干", answer: "A", explanation: "解析" }, { mistakeBook: [], excellentBook: [] });
assert.ok(wrongTeacherCard.includes("去问AI老师"));
assert.ok(!correctTeacherCard.includes("去问AI老师"));
const longCatPayload = context.prepareChatCompletionPayload({ model: "LongCat-2.0", response_format: { type: "json_object" }, messages: [] });
assert.equal(longCatPayload.response_format, undefined);
assert.equal(longCatPayload.thinking.type, "disabled");
const readerChunks = [
  { id: "r1", fileId: "reader", fileName: "阅读.pdf", page: 3, paragraph: 1, text: "身份认证用于确认通信实体身份。", knowledgePoint: "身份认证" },
  { id: "r2", fileId: "reader", fileName: "阅读.pdf", page: 3, paragraph: 2, text: "认证协议需要抵抗重放攻击。", knowledgePoint: "认证协议" },
  { id: "r3", fileId: "reader", fileName: "阅读.pdf", page: 4, paragraph: 1, text: "访问控制用于限制资源使用权限。", knowledgePoint: "访问控制" }
];
const readerRetrieved = context.retrieveChunksForBlueprintSlot(readerChunks, {
  readerPageKey: "reader|3",
  knowledgePoint: "",
  focus: "核心概念与边界",
  cognitiveLevel: "理解"
}, { subjectAnalysis: { name: "网络安全" }, subjectSelection: {} }, { scope: "reader_pages", scopeChapter: "" }, 3);
assert.ok(readerRetrieved.length > 0);
assert.ok(readerRetrieved.every((chunk) => chunk.page === 3));
assert.equal(context.resolveGeneratedKnowledgePoint("从允许来源中确定", [{ text: "AES采用分组密码结构完成加密。", knowledgePoint: "AES算法结构" }], "engineering"), "AES算法结构");
assert.notEqual(context.resolveGeneratedKnowledgePoint("从允许来源中确定", [{ text: "AES采用分组密码结构完成加密。" }], "engineering"), "从允许来源中确定");
assert.equal(context.resolveGeneratedKnowledgePoint("从允许来源中确定", [{ text: "对 轮 密 铜 加 步 骤 , 反 ...", knowledgePoint: "对 轮 密 铜 加 步 骤 , 反 ..." }], "engineering", "在DES算法的解密过程中，下列操作哪一项正确？"), "DES算法");

const tocMarkers = context.parseAllBookChapterMarkers("目录\n第1章 哈希函数 ...... 1\n第2章 消息认证 ...... 11\n第3章 访问控制 ...... 21", { fullText: true });
assert.deepEqual(Array.from(tocMarkers.map((marker) => marker.listedPage)), [1, 11, 21]);
const boundaryCourse = {
  directoryOutline: {},
  directoryPageOutline: {},
  chunks: [
    { id: "toc", fileId: "book", fileName: "教材.pdf", page: 5, paragraph: 1, text: "目录\n第1章 哈希函数 ...... 1\n第2章 消息认证 ...... 11\n第3章 访问控制 ...... 21" },
    { id: "bc1", fileId: "book", fileName: "教材.pdf", page: 20, paragraph: 1, text: "第1章 哈希函数" },
    { id: "bc2", fileId: "book", fileName: "教材.pdf", page: 30, paragraph: 1, text: "第2章 消息认证" },
    { id: "bc3", fileId: "book", fileName: "教材.pdf", page: 40, paragraph: 1, text: "访问控制策略规定主体对资源的使用权限。" }
  ]
};
context.assignStructuralChapters(boundaryCourse);
assert.equal(boundaryCourse.chunks.find((chunk) => chunk.id === "bc3").structuralChapter, "第3章 · 访问控制");
assert.equal(Object.keys(boundaryCourse.directoryOutline.book).length, 3);
assert.equal(boundaryCourse.directoryPageOutline.book["chapter:3"], 21);

const twelveNames = [..."甲乙丙丁戊己庚辛壬癸子丑"].map((suffix) => `安全主题${suffix}`);
const twelveToc = "目录\n" + Array.from({ length: 12 }, (_, index) => `第${index + 1}章 ${twelveNames[index]} ...... ${index * 10 + 1}`).join("\n");
const twelveCourse = {
  directoryOutline: {},
  directoryPageOutline: {},
  chunks: [
    { id: "toc12", fileId: "book12", fileName: "十二章教材.pdf", page: 4, paragraph: 1, text: twelveToc },
    ...Array.from({ length: 12 }, (_, index) => ({
      id: `chapter${index + 1}`,
      fileId: "book12",
      fileName: "十二章教材.pdf",
      page: index * 10 + 20,
      paragraph: 1,
      text: index < 8 ? `第${index + 1}章 ${twelveNames[index]}` : `这里是${twelveNames[index]}的课程正文内容。`
    }))
  ]
};
context.assignStructuralChapters(twelveCourse);
const twelveAssigned = new Set(twelveCourse.chunks.filter((chunk) => chunk.id !== "toc12").map((chunk) => chunk.structuralChapter));
assert.equal(twelveAssigned.size, 12);
assert.ok([...twelveAssigned].some((chapter) => chapter.startsWith("第12章")));
assert.equal(context.isTableOfContentsChunk("第1章 TLS 1.3", 20), false);

console.log("knowledge logic smoke test passed");
