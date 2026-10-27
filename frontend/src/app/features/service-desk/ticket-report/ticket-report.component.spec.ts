import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';

import { TicketsReport } from '../sla.service';
import { TicketReportComponent, isoDay } from './ticket-report.component';

const group = (key: string, met: number, breached: number) => ({
  key, label: key, met, breached, compliance_percent: met + breached ? (met * 100) / (met + breached) : null,
  avg_first_response_minutes: met + breached ? 30 : null, avg_resolution_minutes: met + breached ? 150 : null
});

const REPORT: TicketsReport = {
  start: '2026-10-01', end: '2026-10-27', total_tickets: 3, resolution_rate_percent: 66.7,
  by_status: { OPENED: 1, RESOLVED: 2 }, by_priority: { HIGH: 3 }, by_category: [{ category: 'Rede', count: 3 }],
  sla: {
    total: group('total', 1, 1), by_priority: [group('HIGH', 1, 1)], by_category: [group('Rede', 1, 1)],
    open: 2, at_risk: 1, overdue: 1,
    attention: [
      { ticket_id: 't1', title: 'Sem rede', priority: 'HIGH', kind: 'FIRST_RESPONSE', due_at: '2026-10-27T15:00:00Z', overdue: true },
      { ticket_id: 't2', title: 'Impressora', priority: 'LOW', kind: 'RESOLUTION', due_at: '2026-10-28T15:00:00Z', overdue: false }
    ]
  }
};

async function mount() {
  await TestBed.configureTestingModule({
    imports: [TicketReportComponent],
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
  }).compileComponents();
  const fixture = TestBed.createComponent(TicketReportComponent);
  const http = TestBed.inject(HttpTestingController);
  fixture.detectChanges();
  return { fixture, cmp: fixture.componentInstance, http };
}

describe('TicketReportComponent', () => {
  it('opens on the current month and shows the SLA indicators', async () => {
    const { fixture, cmp, http } = await mount();
    const today = new Date();
    const req = http.expectOne((r) => r.url === '/api/v1/tickets/reports/summary');
    expect(req.request.params.get('start')).toBe(isoDay(new Date(today.getFullYear(), today.getMonth(), 1)));
    expect(req.request.params.get('end')).toBe(isoDay(today));
    req.flush(REPORT);
    fixture.detectChanges();
    expect(cmp.report).toEqual(REPORT);
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('[data-testid="report-compliance"]')?.textContent).toContain('50%');
    expect(el.textContent).toContain('2 h 30 min');
    const rows = el.querySelectorAll('[data-testid="report-attention"] tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('Atrasado');
    expect(rows[1].textContent).toContain('Em risco');
  });

  it('asks for the whole history without dates and shows a dash when nothing finished', async () => {
    const { fixture, cmp, http } = await mount();
    http.expectOne((r) => r.url === '/api/v1/tickets/reports/summary').flush(REPORT);
    cmp.allTime();
    const req = http.expectOne((r) => r.url === '/api/v1/tickets/reports/summary');
    expect(req.request.params.keys()).toEqual([]);
    req.flush({ ...REPORT, sla: { ...REPORT.sla, total: group('total', 0, 0), attention: [] } });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="report-compliance"]')?.textContent).toContain('—');
  });

  it('shows the API error instead of an empty report', async () => {
    const { fixture, cmp, http } = await mount();
    http.expectOne((r) => r.url === '/api/v1/tickets/reports/summary').flush(
      { detail: 'A data inicial deve ser anterior ou igual à final.' }, { status: 422, statusText: 'Unprocessable' }
    );
    fixture.detectChanges();
    expect(cmp.error).toBeTruthy();
    expect(fixture.nativeElement.querySelector('[data-testid="report-cards"]')).toBeNull();
  });

  it('formats a local day without shifting it to UTC', () => {
    expect(isoDay(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05');
  });
});
