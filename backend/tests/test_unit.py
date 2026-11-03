import pytest
from app.pdf_processing import extract_chunks, InvalidPDF
from app.qa import validate_paragraph, INSUFFICIENT
from app.config import Settings
from app.model_service import _parse_embeddings, ModelError
from .pdf_factory import pdf


def test_chinese_page_mapping():
    pages, chunks = extract_chunks(
        pdf(
            [
                "青禾项目第一阶段预算为三百万元。城市绿化是本项目的重要组成部分。",
                "第二阶段计划于二零二七年完成。建设内容是社区公共空间更新与无障碍设施改善。",
            ]
        )
    )
    assert pages == 2
    assert chunks[0]["page"] == 1 and "三百万元" in chunks[0]["text"]
    assert chunks[1]["page"] == 2 and chunks[1]["ordinal"] == 1


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"", "为空"),
        (b"bad", "有效"),
        (pdf(encrypted=True), "加密"),
        (pdf(blank=True), "扫描件"),
        (pdf(["内容"] * 101), "100"),
    ],
    ids=["empty", "invalid", "encrypted", "scan", "page-limit"],
)
def test_invalid_pdfs(data, reason):
    with pytest.raises(InvalidPDF, match=reason):
        extract_chunks(data)


def test_citation_gate():
    sources = [{"label": 1}, {"label": 3}]
    assert validate_paragraph("预算是三百万元。[1]", sources)[1] == {1}
    assert validate_paragraph("无依据的结论。", sources) == ("", set())
    assert validate_paragraph("编造来源。[2]", sources) == ("", set())
    assert validate_paragraph("混入伪造引用。[1][99]", sources) == ("", set())
    assert INSUFFICIENT in validate_paragraph(INSUFFICIENT, sources)[0]


def test_dimension_validation():
    with pytest.raises(ModelError):
        _parse_embeddings({"data": [{"index": 0, "embedding": [1, 2]}]}, 1)


def test_production_rejects_development_secrets():
    with pytest.raises(ValueError):
        Settings(environment="production")
