"""Release-only metadata lookup; product downloads use the committed manifest."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Qwen/Qwen3-VL-8B-Instruct-GGUF'
RUNTIME = {
    'llama-b11429-bin-win-cuda-12.4-x64.zip': 'dd6df685c1024e6aa55ca55ad35038692d5e284d4dc895e7a646c3245d3d14ff',
    'cudart-llama-bin-win-cuda-12.4-x64.zip': '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6',
}
MODEL = {
    'Qwen3VL-8B-Instruct-Q4_K_M.gguf': '67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2',
    'mmproj-Qwen3VL-8B-Instruct-F16.gguf': 'ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38',
}


def get(url):
    with urlopen(Request(url,headers={'User-Agent':'Vision-release-lock'}),timeout=30) as response:
        return json.load(response)


def main():
    metadata = get(f'https://huggingface.co/api/models/{REPOSITORY}?blobs=true')
    release = get('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11429')
    records = []
    assets = {a['name']:a for a in release['assets']}
    for name,sha in RUNTIME.items():
        asset = assets[name]
        if asset.get('digest') != 'sha256:'+sha:
            raise ValueError('Runtime digest changed: '+name)
        records.append(dict(asset_id=name,filename=name,version='b11429',download_url=asset['browser_download_url'],
                            size_bytes=asset['size'],sha256=sha,destination='downloads/'+name))
    files = {a['rfilename']:a for a in metadata['siblings']}
    for name,sha in MODEL.items():
        info = files[name]['lfs']
        if info['sha256'] != sha:
            raise ValueError('Model digest changed: '+name)
        records.append(dict(asset_id=name,filename=name,repository_revision=metadata['sha'],
            download_url=f"https://huggingface.co/{REPOSITORY}/resolve/{metadata['sha']}/{name}",
            size_bytes=info['size'],sha256=sha,destination='models/'+name))
    path = ROOT/'src/local_vision_solver/assets.lock.json'
    path.write_text(json.dumps({'schema_version':1,'assets':records},indent=2)+'\n',encoding='utf-8')
    print('Pinned asset metadata: '+str(path))
    print('HF revision: '+metadata['sha'])


if __name__=='__main__':
    main()
