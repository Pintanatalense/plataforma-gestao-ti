import { TestBed } from '@angular/core/testing';

import { SlaInfo } from '../sla.service';
import { SlaBadgeComponent } from './sla-badge.component';

async function render(sla: SlaInfo | null) {
  await TestBed.configureTestingModule({ imports: [SlaBadgeComponent] }).compileComponents();
  const fixture = TestBed.createComponent(SlaBadgeComponent);
  fixture.componentRef.setInput('sla', sla);
  fixture.detectChanges();
  return fixture.nativeElement.querySelector('[data-testid="sla-badge"]') as HTMLElement | null;
}

describe('SlaBadgeComponent', () => {
  it('shows nothing when the ticket has no SLA', async () => {
    expect(await render({ state: 'NOT_APPLICABLE' })).toBeNull();
    TestBed.resetTestingModule();
    expect(await render(null)).toBeNull();
  });

  it('shows the first response deadline while waiting for it', async () => {
    const badge = await render({
      state: 'RUNNING', policy_name: 'Padrão', first_response_due_at: '2026-10-26T15:00:00Z', resolution_due_at: '2026-10-27T14:00:00Z'
    });
    expect(badge?.textContent).toContain('No prazo');
    expect(badge?.textContent).toContain('responder até');
    expect(badge?.className).toContain('running');
  });

  it('switches to the resolution deadline after the first response', async () => {
    const badge = await render({
      state: 'RUNNING', first_response_due_at: '2026-10-26T15:00:00Z', first_response_at: '2026-10-26T14:30:00Z',
      resolution_due_at: '2026-10-27T14:00:00Z'
    });
    expect(badge?.textContent).toContain('resolver até');
  });

  it('marks a running ticket with a registered breach as violated', async () => {
    const badge = await render({ state: 'RUNNING', resolution_due_at: '2026-10-27T14:00:00Z', breaches: ['FIRST_RESPONSE'] });
    expect(badge?.textContent).toContain('Violado');
    expect(badge?.className).toContain('breached');
  });

  it('shows paused and met without a deadline', async () => {
    expect((await render({ state: 'PAUSED', paused: true }))?.textContent).toContain('Pausado');
    TestBed.resetTestingModule();
    const met = await render({ state: 'MET', resolved_at: '2026-10-26T18:00:00Z' });
    expect(met?.textContent).toContain('Cumprido');
    expect(met?.textContent).not.toContain('até');
  });
});
