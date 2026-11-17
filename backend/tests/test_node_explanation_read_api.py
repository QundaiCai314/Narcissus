from .test_directory_branch_api import setup
from app import node_explanations


def test_directory_get_and_post_reject_before_generation(setup,monkeypatch):
    client,db,_,_=setup
    def forbidden(*args):raise AssertionError('Directory must not generate or read body evidence')
    monkeypatch.setattr(node_explanations,'explain',forbidden)
    for method in [client.get,client.post]:
        response=method('/learning/original/nodes/chapter/explanation')
        assert response.status_code==409,response.text
        assert response.json()['detail']['code']=='directory_only'
