import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { TicketListComponent } from './ticket-list.component';

const base = { description: 'd', status: 'OPENED', priority: 'HIGH', requester_id: 'e', created_at: '2026-10-26T14:00:00Z' };
const TICKETS = [
  { ...base, id: 't1', title: 'Sem SLA', sla: { state: 'NOT_APPLICABLE' } },
  { ...base, id: 't2', title: 'No prazo', sla: { state: 'RUNNING' } },
  { ...base, id: 't3', title: 'Em risco', sla: { state: 'RUNNING', at_risk: true } },
  { ...base, id: 't4', title: 'Atrasado', sla: { state: 'RUNNING', overdue: true } },
  { ...base, id: 't5', title: 'Violado e resolvido', status: 'RESOLVED', sla: { state: 'BREACHED', breaches: ['RESOLUTION'] } }
];

describe('TicketListComponent', () => {
  let component: TicketListComponent;
  let fixture: ComponentFixture<TicketListComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TicketListComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(TicketListComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  function load(tickets: unknown[]) {
    http.expectOne('/api/v1/tickets').flush(tickets);
    fixture.detectChanges();
  }

  const titles = () => component.visibleTickets.map((t) => t.title);

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('shows the SLA column and filters by SLA situation', () => {
    load(TICKETS);
    expect(fixture.nativeElement.querySelector('[data-testid="sla-filter"]')).toBeTruthy();
    expect(fixture.nativeElement.querySelectorAll('[data-testid="sla-badge"]').length).toBe(4);
    expect(titles().length).toBe(5);

    component.setSlaFilter('attention');
    expect(titles()).toEqual(['Em risco', 'Atrasado']);
    component.setSlaFilter('breached');
    expect(titles()).toEqual(['Atrasado', 'Violado e resolvido']);
    component.setSlaFilter('all');
    expect(titles().length).toBe(5);
  });

  it('hides the SLA filter when no ticket has SLA', () => {
    load([TICKETS[0]]);
    expect(fixture.nativeElement.querySelector('[data-testid="sla-filter"]')).toBeNull();
  });
});
