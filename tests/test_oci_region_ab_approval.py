"""Owner-only robots-first two-arm execution gate (offline, no site)."""
import unittest
from app_v5.region_ab_sample import RegionABSession
from ops.oci.region_ab import run, _APPROVAL


class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_denial_happens_before_any_network(self):
        calls=[]
        def forbidden(*args,**kwargs):
            calls.append("called")
            raise AssertionError("Network must not start")
        value=await run(live=True,headed=True,approval="BAD",
                        directory_check=forbidden,robots=forbidden,
                        picker_robots=forbidden)
        self.assertEqual(value["status"],"OWNER_APPROVAL_REQUIRED")
        self.assertEqual(calls,[])

    async def test_denied_second_picker_blocks_before_browser(self):
        called=[]
        def picker(term):
            called.append(term)
            return {"allowed":term=="불당동"}
        out=await run(live=True,headed=True,approval=_APPROVAL,
                      directory_check=lambda:True,robots=lambda:True,
                      picker_robots=picker,
                      experiment=lambda:None)
        self.assertEqual(out["status"],"ROBOTS_NOT_ALLOWED")
        self.assertEqual(called,["불당동","배방읍"])
        self.assertFalse(out["authorizes_listings"])

    async def test_fake_experiment_after_all_gates_returns_nonsensitive_result(self):
        async def sample():
            return RegionABSession(secret=b"Z"*32).summarize({}, {})
        out=await run(live=True,headed=True,approval=_APPROVAL,
                      directory_check=lambda:True,robots=lambda:True,
                      picker_robots=lambda term:{"allowed":True},
                      experiment=sample)
        self.assertEqual(out["status"],"INCOMPLETE")
        self.assertFalse(out["authorizes_listings"])
        self.assertFalse(out["database_written"])


if __name__=="__main__":
    unittest.main()
