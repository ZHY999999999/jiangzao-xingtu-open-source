"""Real local L + seven approval/projection/catalogue regressions; synthetic only."""
import sys
sys.dont_write_bytecode = True
import copy
import json
import unittest
from datetime import datetime, timezone
import test_catalogue as legacy

gate = legacy.gate
projection = gate.projection
CODE = legacy.fixtures.CODE

class OverviewCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.base = legacy.CatalogueTests('test_three_contents_not_eight_deep_union')
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.f = self.base.f.fixture
        self.root, self.app = self.base.root, self.base.app
        self.bundle = f'inbox/{CODE}/v002'
        self.review = f'reviews/{CODE}/v002/review.json'
        self.page = f'reviews/{CODE}/v002/page-review.json'
        old = self.root / self.f.bundle_path
        self.reader = json.loads((old / 'reader.json').read_bytes())
        self.reader.update(contentTier='L', asOf='2026-01-01')
        self.reader['answers'] = self.reader['answers'][:2]
        self.reader['businessModel'] = {'flows':[{'id':'f1',
            'buyer':{'text':'Synthetic buyer only','claimIds':['c1']},
            'work':{'text':'Synthetic delivery only','claimIds':['c2']},
            'income':{'text':'Synthetic income 12.30 only','claimIds':['graph']}}],
            'notes':[{'text':'Synthetic graph limitation only','claimIds':['graph']}]}
        evidence = json.loads((old / 'evidence.json').read_bytes())
        evidence['claims'] = evidence['claims'][:2]
        evidence['claims'].append({**copy.deepcopy(evidence['claims'][1]), 'id':'graph', 'claim':'Synthetic income 12.30 only'})
        sources = json.loads((old / 'sources.json').read_bytes())
        for name, value in [('reader.json',self.reader),('evidence.json',evidence),('sources.json',sources)]:
            self.f.put(self.root / self.bundle / name, value)
        (self.root / self.bundle / '读者稿.md').write_text('SYNTHETIC ONLY', encoding='utf-8')
        self.f.put(self.root / self.bundle / 'manifest.json', {'schemaVersion':1,'jobId':gate.chain.checker.JOB_ID,'code':CODE,
            'files':[{'path':p.name,'sha256':gate.chain.sha(p.read_bytes())} for p in sorted((self.root/self.bundle).iterdir())]})
        digest = gate.chain.sha((self.root/self.bundle/'manifest.json').read_bytes())
        self.f.put(self.root/self.bundle/'ready.json', {'schemaVersion':1,'jobId':gate.chain.checker.JOB_ID,'code':CODE,
            'manifestSha256':digest,'completedAt':datetime.now(timezone.utc).isoformat(),
            'producer':{'id':'SYNTHETIC PRODUCER','runId':'10000000-0000-4000-8000-000000000001'}})
        self.f.put(self.root/self.review, {'schemaVersion':1,'jobId':gate.chain.checker.JOB_ID,'code':CODE,
            'bundlePath':self.bundle,'manifestSha256':digest,'contentDecision':'approved','contentTier':'L',
            'reviewer':'SYNTHETIC INDEPENDENT REVIEWER','reviewedAt':datetime.now(timezone.utc).isoformat(),
            'reviewedClaimIds':['c1','c2','graph'],'scope':'Synthetic only, no company facts approved.',
            'checks':{key:{'decision':'passed','reason':'Synthetic contract fixture'} for key in gate.chain.builder.L_CHECKS}})
        built=gate.chain.builder.build_candidate(self.root,self.bundle,self.review,'overview-fixture')
        self.assertEqual(built['status'],'local_candidate_built',built)
        self.f.put(self.root/self.page, {'schemaVersion':1,'jobId':gate.chain.checker.JOB_ID,'code':CODE,
            'manifestSha256':digest,'candidatePath':built['candidatePath'],'htmlSha256':built['htmlSha256'],
            'pageDecision':'passed','reviewer':'SYNTHETIC PAGE REVIEWER','reviewedAt':datetime.now(timezone.utc).isoformat(),
            'contentTier':'L','rendererSha256':built['rendererSha256'],
            'browserChecks':{'desktop':True,'narrow':True,'evidenceExpanded':True}})
        result=projection.project_company(self.root,CODE,'L')
        self.assertEqual(result['status'],'local_content_projected',result)
        self.projected=self.root/result['outputs'][0]['path']
        self.content=self.app/'content/company-overview'/f'{CODE}.json'
        self.content.parent.mkdir()
        self.content.write_bytes((self.projected/'content.json').read_bytes())
        self.base.selection['overviews']=[{'code':CODE,'sha256':gate.chain.sha(self.content.read_bytes())}]
        self.base.seal_selection()

    def run_gate(self):
        return self.base.run_gate()

    def test_same_company_two_tiers_independently_approved_and_counted_once(self):
        result=self.run_gate(); entry=next(r for r in result['catalogue']['entries'] if r['code']==CODE)
        self.assertEqual(entry['kind'],'seven-questions')
        self.assertEqual(entry['overview']['contentSha256'],gate.chain.sha(self.content.read_bytes()))
        self.assertEqual(result['catalogue']['counts'],{'readable':3,'legacy':2,'reviewedSeven':1,'reviewedOverview':1})
        self.assertEqual(result['adoptions'][0]['selectedInput']['version'],'v001')
        self.assertEqual(result['overviewAdoptions'][0]['selectedInput']['version'],'v002')
        public=json.loads(self.content.read_bytes())
        self.assertEqual(public['businessModel'],self.reader['businessModel'])
        self.assertEqual({c['id'] for c in public['claims']},{'c1','c2','graph'})

    def test_overview_only_does_not_become_seven(self):
        self.base.selection['sevenQuestions']=[]; self.base.content.unlink(); self.base.content.parent.rmdir(); self.base.seal_selection()
        result=self.run_gate();entry=next(r for r in result['catalogue']['entries'] if r['code']==CODE)
        self.assertEqual(entry['kind'],'business-overview');self.assertEqual(entry['audio'],'none')
        self.assertEqual(result['catalogue']['counts'],{'readable':3,'legacy':2,'reviewedSeven':0,'reviewedOverview':1})

    def test_new_l_draft_blocks_l_but_preserves_latest_legacy(self):
        self.f.put(self.root/f'inbox/{CODE}/v003/reader.json',self.reader)
        self.assertEqual(gate.chain.check_selection(self.root,[CODE])['status'],'verified_for_conversion_inputs')
        result=gate.chain.check_selection(self.root,[CODE],'L')
        self.assertEqual(result['status'],'rejected');self.assertEqual(result['errors'][0]['code'],'latest_not_ready')

    def test_new_seven_draft_blocks_seven_but_preserves_l(self):
        old=json.loads((self.root/self.f.bundle_path/'reader.json').read_bytes())
        self.f.put(self.root/f'inbox/{CODE}/v003/reader.json',old)
        self.assertEqual(gate.chain.check_selection(self.root,[CODE],'L')['status'],'verified_for_conversion_inputs')
        self.assertEqual(gate.chain.check_selection(self.root,[CODE])['errors'][0]['code'],'latest_not_ready')

    def test_new_approved_seven_after_l_keeps_latest_in_each_tier(self):
        self.f.make_chain(CODE, 'v003')
        deep = gate.chain.check_selection(self.root, [CODE])
        overview = gate.chain.check_selection(self.root, [CODE], 'L')
        self.assertEqual(deep['status'], 'verified_for_conversion_inputs', deep)
        self.assertEqual(overview['status'], 'verified_for_conversion_inputs', overview)
        self.assertEqual(deep['acceptedInputs'][0]['version'], 'v003')
        self.assertEqual(overview['acceptedInputs'][0]['version'], 'v002')

    def test_l_queue_observation_cannot_supersede_legacy_approval(self):
        self.f.state['observations'][CODE]={'version':'v002','contentTier':'L','status':'complete'}
        self.f.save_state()
        self.assertEqual(self.run_gate()['adoptions'][0]['selectedInput']['version'],'v001')

    def test_missing_graph_review_and_page_chain_reject_live(self):
        self.f.edit(self.review,lambda row:row.update(reviewedClaimIds=['c1','c2']))
        with self.assertRaisesRegex(ValueError,'Current overview approval rejected'):self.run_gate()

    def test_public_snapshot_carries_two_hashes_without_live_qualification(self):
        result=self.run_gate();snapshot=gate.public_snapshot(result,self.base.selection)
        self.f.put(self.app/'content-approval-snapshot.json',snapshot)
        restored=gate.verify_snapshot(self.app,self.app/'public')
        self.assertEqual(restored['overviewAdoptions'],[]);self.assertIsNone(restored['overviewApprovalBindingId'])
        self.assertFalse(restored['readyForPublication'])
        self.assertEqual(len(snapshot['approvedOverview']),1);self.assertEqual(len(snapshot['approvedSeven']),1)
        (self.root/self.page).unlink()
        self.assertEqual(gate.verify_snapshot(self.app,self.app/'public')['approvalMode'],'public-snapshot')
        with self.assertRaisesRegex(ValueError,'Current overview approval rejected'):self.run_gate()

    def test_overview_content_tampering_even_rehashed_selection_is_rejected(self):
        value=json.loads(self.content.read_bytes());value['businessModel']['flows'][0]['income']['text']='Synthetic changed 99'
        self.f.put(self.content,value)
        self.base.selection['overviews'][0]['sha256']=gate.chain.sha(self.content.read_bytes());self.base.seal_selection()
        with self.assertRaisesRegex(ValueError,'currently approved text'):self.run_gate()

if __name__ == '__main__': unittest.main()
