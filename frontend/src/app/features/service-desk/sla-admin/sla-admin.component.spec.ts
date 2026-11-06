import { TestBed } from '@angular/core/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';

import { SlaCalendar, SlaPolicy, SlaService } from '../sla.service';
import { SlaAdminComponent } from './sla-admin.component';

const CALENDAR: SlaCalendar = {
  id: 'c1', name: 'Horário comercial', timezone: 'America/Sao_Paulo',
  weekly_hours: { '0': [['08:00', '12:00'], ['13:00', '18:00']] }, holidays: [{ day: '2026-12-25', name: 'Natal' }],
  policy_names: ['Padrão']
};
const POLICY: SlaPolicy = {
  id: 'p1', name: 'Padrão', description: null, is_active: false, calendar_id: 'c1', calendar_name: 'Horário comercial',
  pause_statuses: ['PENDING'], reopen_rule: 'RESTART', alert_percent: 80,
  targets: [{ priority: 'HIGH', first_response_minutes: 60, resolution_minutes: 480 }], category_names: []
};

async function mount(api: Partial<Record<keyof SlaService, unknown>>) {
  const service = {
    listPolicies: vi.fn().mockReturnValue(of([POLICY])),
    listCalendars: vi.fn().mockReturnValue(of([CALENDAR])),
    ...api
  };
  await TestBed.configureTestingModule({
    imports: [SlaAdminComponent],
    providers: [provideNoopAnimations(), provideRouter([]), { provide: SlaService, useValue: service }]
  }).compileComponents();
  const fixture = TestBed.createComponent(SlaAdminComponent);
  fixture.componentInstance['snackBar'] = { open: vi.fn() } as unknown as MatSnackBar;
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, cmp: fixture.componentInstance, service };
}

describe('SlaAdminComponent', () => {
  it('lists policies with their targets, calendar and status', async () => {
    const { fixture } = await mount({});
    const card: HTMLElement = fixture.nativeElement.querySelector('[data-testid="policy-Padrão"]');
    expect(card.textContent).toContain('Inativa');
    expect(card.textContent).toContain('Alta');
    expect(card.textContent).toContain('1 h');
    expect(card.textContent).toContain('8 h');
    expect(card.textContent).toContain('nenhuma (ligue em Categorias de Chamados)');
  });

  it('creates a policy converting hours to business minutes', async () => {
    const createPolicy = vi.fn().mockReturnValue(of(POLICY));
    const { cmp } = await mount({ createPolicy });
    cmp.newPolicy();
    const d = cmp.policyDraft!;
    d.name = 'Ouro';
    const critical = d.targets.find((t) => t.code === 'CRITICAL')!;
    Object.assign(critical, { enabled: true, firstHours: 0.5, resolutionHours: 4 });
    d.pauseInProgress = true;
    cmp.savePolicy();

    expect(createPolicy).toHaveBeenCalledWith({
      name: 'Ouro', description: null, calendar_id: 'c1', is_active: false, alert_percent: 80, reopen_rule: 'RESTART',
      pause_statuses: ['IN_PROGRESS', 'PENDING'],
      targets: [{ priority: 'CRITICAL', first_response_minutes: 30, resolution_minutes: 240 }]
    });
    expect(cmp.policyDraft).toBeNull();
  });

  it('refuses a resolution shorter than the first response without calling the API', async () => {
    const createPolicy = vi.fn();
    const { cmp } = await mount({ createPolicy });
    cmp.newPolicy();
    cmp.policyDraft!.name = 'Errada';
    Object.assign(cmp.policyDraft!.targets[0], { enabled: true, firstHours: 4, resolutionHours: 1 });
    cmp.savePolicy();
    expect(createPolicy).not.toHaveBeenCalled();
    expect(cmp.policyError).toContain('não pode ser menor');
  });

  it('keeps the form open and shows the API message when saving fails', async () => {
    const updatePolicy = vi.fn().mockReturnValue(
      throwError(() => ({ status: 409, error: { error: { message: 'Já existe uma política com esse nome' } } }))
    );
    const { cmp } = await mount({ updatePolicy });
    cmp.editPolicy(POLICY);
    expect(cmp.policyDraft!.targets.find((t) => t.code === 'HIGH')).toMatchObject({ enabled: true, firstHours: 1, resolutionHours: 8 });
    cmp.savePolicy();
    expect(cmp.policyError).toBe('Já existe uma política com esse nome');
    expect(cmp.policyDraft).not.toBeNull();
  });

  it('saves a calendar with lunch break and holidays in the API format', async () => {
    const updateCalendar = vi.fn().mockReturnValue(of(CALENDAR));
    const { cmp } = await mount({ updateCalendar });
    cmp.editCalendar(CALENDAR);
    cmp.calendarDraft!.days[5].intervals.push({ start: '08:00', end: '12:00' });
    cmp.saveCalendar();
    expect(updateCalendar).toHaveBeenCalledWith('c1', {
      name: 'Horário comercial', timezone: 'America/Sao_Paulo',
      weekly_hours: { '0': [['08:00', '12:00'], ['13:00', '18:00']], '5': [['08:00', '12:00']] },
      holidays: [{ day: '2026-12-25', name: 'Natal' }]
    });
  });

  it('summarizes the calendar by weekday', async () => {
    const { cmp } = await mount({});
    const lines = cmp.hoursSummary(CALENDAR);
    expect(lines[0]).toBe('Segunda: 08:00–12:00, 13:00–18:00');
    expect(lines[6]).toBe('Domingo: sem expediente');
    expect(cmp.holidaysSummary(CALENDAR)).toBe('25/12/2026 Natal');
  });

  it('shows a load failure instead of an empty list', async () => {
    const { fixture } = await mount({ listPolicies: vi.fn().mockReturnValue(throwError(() => ({ status: 500 }))) });
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('[data-testid="state-empty"]')).toBeFalsy();
  });
});
