import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { TicketCreateComponent } from './ticket-create.component';

describe('Abrir chamado com subchamados e modelo (ADR-026)', () => {
  let fixture: ComponentFixture<TicketCreateComponent>;
  let component: TicketCreateComponent;
  let backend: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [TicketCreateComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideNoopAnimations(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({}), queryParamMap: convertToParamMap({}) } } }
      ]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(TicketCreateComponent);
    component = fixture.componentInstance;
    (component as unknown as { snackBar: MatSnackBar }).snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    fixture.detectChanges();
    backend.match((r) => r.url !== '/api/v1/ticket-templates');
    backend.expectOne('/api/v1/ticket-templates').flush([
      { id: 'tpl', name: 'Processo', is_active: true, items: [
        { category_id: 'cat-b', title: 'Etapa B', description: 'faz B', is_required: true, default_custom_fields: { x: 1 } },
        { category_id: 'cat-c', title: 'Etapa C', description: 'faz C', is_required: false }
      ] }
    ]);
  });

  it('fills the rows from a template and sends them as children with the template id', () => {
    component.applyTemplate('tpl');
    expect(component.childSpecs.map((s) => s.title)).toEqual(['Etapa B', 'Etapa C']);
    component.childSpecs[1].title = 'Etapa C editada';
    component.ticketForm.patchValue({ title: 'Processo', description: 'Descrição' });
    component.onSubmit();
    const req = backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/tickets');
    expect(req.request.body.template_id).toBe('tpl');
    expect(req.request.body.children.map((c: { title: string }) => c.title)).toEqual(['Etapa B', 'Etapa C editada']);
    expect(req.request.body.children[0].custom_fields).toEqual({ x: 1 });
    expect(req.request.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('keeps the same idempotency key when the user retries after an error', async () => {
    component.ticketForm.patchValue({ title: 'Pedido', description: 'Descrição' });
    component.onSubmit();
    const first = backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/tickets');
    const key = first.request.headers.get('Idempotency-Key');
    first.flush({ error: { message: 'x' } }, { status: 500, statusText: 'x' });
    component.onSubmit();
    const retry = backend.expectOne((r) => r.method === 'POST' && r.url === '/api/v1/tickets');
    expect(retry.request.headers.get('Idempotency-Key')).toBe(key);
  });

  it('refuses to submit an incomplete child row', () => {
    component.addChildRow();
    component.ticketForm.patchValue({ title: 'Pedido', description: 'Descrição' });
    expect(component.childrenValid()).toBe(false);
    component.onSubmit();
    backend.expectNone((r) => r.method === 'POST' && r.url === '/api/v1/tickets');
  });
});