"""Object archive with exact object keys. Used with a quiesced database snapshot."""

import json
import sys
import tarfile
import io
from sqlalchemy import select
from .db import SessionLocal
from .models import Document, SourceVersion, AudioBlob, VisualFile
from . import storage


def backup(path):
    manifest = []
    with SessionLocal() as db, tarfile.open(path, "w:gz") as archive:
        objects = {}
        for doc in db.scalars(select(Document)):
            objects[doc.object_key] = doc.status == "uploading" or bool(doc.deleted_at)
        for version in db.scalars(select(SourceVersion)):
            objects[version.object_key] = objects.get(version.object_key, version.status in ("queued", "failed", "cancelled"))
        for blob in db.scalars(select(AudioBlob)):
            objects[blob.object_key] = blob.status != "ready"
        for visual in db.scalars(select(VisualFile)):
            objects[visual.object_key] = visual.status != "ready"
        for index, (key, optional) in enumerate(objects.items()):
            try:
                data = storage.read(key)
            except Exception:
                if optional:
                    continue
                raise
            name = f"files/{index:08d}.bin"
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
            manifest.append({"path": name, "key": key})
        data = json.dumps(manifest, ensure_ascii=False).encode()
        entry = tarfile.TarInfo("manifest.json")
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    print(f"Archived {len(manifest)} private objects.")


def restore(path):
    storage.initialize_bucket()
    with tarfile.open(path, "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        for item in manifest:
            data = archive.extractfile(item["path"]).read()
            storage.put(item["key"], data)
    print(f"Restored {len(manifest)} private objects.")


if __name__ == "__main__":
    {"backup": backup, "restore": restore}[sys.argv[1]](sys.argv[2])
