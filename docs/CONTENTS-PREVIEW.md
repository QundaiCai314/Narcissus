# 目录识别与核对

在笔记本中选择“添加资料 → 只识别目录”。不填页码时只检查PDF书签；没有书签时提示用户指定阅读器里的PDF页码，每次最多12页，不自动扫描全书。

指定页码后，只提取这些页的文本。扫描目录由本地RapidOCR整页识别，识别权重随依赖打包，不访问生成模型或向量API。当前不保证多列目录的版面识别效果。识别在有总超时限制的子进程中运行（独立的`outline_timeout_seconds`，最多600秒）；失败页和未可靠识别的行保留为待核对内容。预览采用后台任务和进度轮询，避免长HTTP请求超时；每个API实例同时只运行一个目录预览。

目录按部分、章、节、小节和附录编号建立父子关系，检查孤立编号、跳号和重复编号。OCR置信度不是准确率；即使没有告警，也应对照原目录核对。标题可编辑，结果可下载为JSON。本阶段只提供预览，不写入资料、对象存储、向量库或正式导图。

`toc_pdf_page`是该目录行所在的PDF物理页；`printed_page`是目录中印刷的正文页码。没有验证二者的对应关系前，`target_pdf_page`保持空值，不用固定偏移猜测正文位置。

接口：`POST /api/notebooks/{id}/outline-preview`，需当前用户拥有笔记本。上传PDF和可选`pages`表单字段，返回`job_id`。使用`GET /api/notebooks/{id}/outline-preview/{job_id}`读取进度与结果。任务仅保存在API进程内存，限所属用户和笔记本访问，20分钟后过期；服务重启后需要重新识别。接口有文件大小、页数和请求频率限制。

验证：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend python -m pytest backend/tests/test_pdf_outline.py -q`。
