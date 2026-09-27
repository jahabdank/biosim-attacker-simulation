"""Earlier static cohorts; these are not replacements by newer recovery protocols."""
import random


def add_historical(save, job):
    def triple(model, trust, story, seed, spacing, *, routed=False):
        rows = [job(model, trust, arm, 'commissioning-receipt' if arm == 'best-sband' else story,
                    repeat, spacing=spacing)
                for arm in ('kill', 'matched-sband', 'best-sband') for repeat in range(1, 7)]
        if routed:
            for row in rows:
                row.update(model_label='grok-4.6', context_window=200000, max_completion_tokens=8192,
                           route='api', cohort_route='route-a', api_backend='chat_completions')
        random.Random(seed).shuffle(rows)
        return rows

    lanes = (
        ('grok-4.6', 'rehearsal-cabin', 15, 'grok46-t0-v1'),
        ('gpt-5.6-luna', 'spare-desk', 15, 'luna-t0-v1'),
        ('grok-4.6-route-a', 'rehearsal-cabin', 40, 'grok46-route-a-t0-v1'),
        ('claude-sonnet-5', 'rehearsal-cabin', 120, 'sonnet-t0-v1'),
    )
    for index, (model, story, spacing, name) in enumerate(lanes):
        seed = 20260920 + index
        save(name, triple(model, 't0', story, seed, spacing, routed=model.endswith('route-a')),
             shuffle_seed=seed, definition='historical/comparison/run_t0_followon.py',
             phase_prerequisites='Original prior-lane status gating is preserved in the archived controller; qualify independently for a fresh cohort.')
    save('grok46-route-a-t1-v1', triple('grok-4.6-route-a', 't1', 'rehearsal-cabin', 20260919, 40, routed=True),
         shuffle_seed=20260919, definition='historical/comparison/run_route_a_grok_triple.py')
    save('grok46-unlabeled-v1', triple('grok-4.6', 'unlabeled', 'rehearsal-cabin', 20260921, 15),
         shuffle_seed=20260921, definition='historical/comparison/run_unlabeled_grok.py')
    for trust in ('t0', 'unlabeled'):
        for index, model in enumerate(('gpt-5.6-terra', 'gpt-5.6-sol')):
            seed = 20260922 + index + (10 if trust == 'unlabeled' else 0)
            save(f'{model}-{trust}-v1', triple(model, trust, 'spare-desk', seed, 15),
                 shuffle_seed=seed, definition='historical/comparison/run_terra_sol_t0_unlabeled.py')
        rows = []
        for index, model in enumerate(('gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra')):
            rows.extend(triple(model, trust, 'spare-desk', 20260923 + index + (10 if trust == 'unlabeled' else 0), .001))
        save(f'gpt6-{trust}-v1', rows, shuffle_seed=20260923,
             definition='historical/comparison/run_gpt6_t0_unlabeled.py',
             phase_prerequisites='Full control and original preceding phase must be distinguished from fresh qualification.')
