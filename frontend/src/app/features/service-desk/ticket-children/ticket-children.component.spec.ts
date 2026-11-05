import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';

import { TicketChildrenComponent } from './ticket-children.component';
import { Ticket } from '../ticket.service';

const PARENT = { id: 'p1', status: 'OPENED', title: 'Processo' } as Ticket;
const OVERVIEW = {
  progress: { total: 2, done: 1, canceled: 0, required_pending: 1, overdue: 1, steps_overdue: 1, process_overdue: false },
  children: [
    { id: 'c1aaaaaaaa', title: 'Compra', status: 'IN_PROGRESS', is_required: true, responsible_sector_id: 's1',
      responsible_sector_name: 'Setor B', created_at: '2026-11-05T10:00:00Z', overdue: true, at_risk: false },
    { id: 'c2bbbbbbbb', title: 'Acesso', status: 'CANCELED', is_required: true, responsible_sector_id: 's2',
      responsible_sector_name: 'Setor C', created_at: '2026-11-05T10:00:00Z', overdue: false, at_risk: false }
  ]
};

describe('Subchamados do chamado principal (ADR-026)', () => {
  let fixture: ComponentFixture<TicketChildrenComponent>;
  let component: TicketChildrenComponent;
  let backend: HttpTestingController;
  let el: HTMLElement;

  const render = (canManage: boolean) => {
    fixture = TestBed.createComponent(TicketChildrenComponent);
    component = fixture.componentInstance;
    (component as unknown as { snackBar: MatSnackBar }).snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    fixture.componentRef.setInput('ticket', PARENT);
    fixture.componentRef.setInput('canAdd', true);
    fixture.componentRef.setInput('canManage', canManage);
    fixture.detectChanges();
    backend.expectOne('/api/v1/tickets/p1/children').flush(OVERVIEW);
    fixture.detectChanges();
    el = fixture.nativeElement as HTMLElement;
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TicketChildrenComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
  });

  it('shows progress, pending steps and the two overdue signals', () => {
    render(false);
    const progress = el.querySelector('[data-testid="children-progress"]')!.textContent!;
    expect(progress).toContain('1 de 2 concluído(s)');
    expect(progress).toContain('1 etapa(s) obrigatória(s) pendente(s)');
    expect(progress).toContain('1 etapa(s) obrigatória(s) atrasada(s)');
    expect(el.querySelectorAll('[data-testid="child-row"]').length).toBe(2);
    expect(el.textContent).toContain('Cancelado');
  });

  it('hides step actions from whoever only follows the process', () => {
    render(false);
    expect(el.querySelectorAll('.actions button').length).toBe(0);
  });

  it('cancels a step only with a justification of at least 10 characters', () => {
    render(true);
    component.start('cancel', OVERVIEW.children[0] as never);
    fixture.detectChanges();
    const confirm = el.querySelector('[data-testid="child-action-confirm"]') as HTMLButtonElement;
    component.reason = 'curto';
    fixture.detectChanges();
    expect(confirm.disabled).toBe(true);

    component.reason = 'Compra feita por outro canal';
    fixture.detectChanges();
    expect(confirm.disabled).toBe(false);
    component.confirmAction();
    const req = backend.expectOne('/api/v1/tickets/c1aaaaaaaa/cancel');
    expect(req.request.body).toEqual({ reason: 'Compra feita por outro canal' });
    req.flush({});
    backend.expectOne('/api/v1/tickets/p1/children').flush(OVERVIEW);
  });

  it('replaces a canceled step with a new required one', () => {
    render(true);
    component.start('replace', OVERVIEW.children[1] as never);
    component.replacement = { category_id: 'cat', title: 'Nova', description: 'd', is_required: false };
    component.reason = 'Fornecedor mudou de setor';
    component.confirmAction();
    const req = backend.expectOne('/api/v1/tickets/c2bbbbbbbb/replace');
    expect(req.request.body.child.is_required).toBe(true);
    req.flush({});
    backend.expectOne('/api/v1/tickets/p1/children').flush(OVERVIEW);
  });

  it('adds children with one idempotency key reused on retry', () => {
    render(true);
    component.startAdd();
    component.newSpecs = [{ category_id: 'cat', title: 'Etapa', description: 'd', is_required: true }];
    component.confirmAdd();
    const first = backend.expectOne('/api/v1/tickets/p1/children');
    const key = first.request.headers.get('Idempotency-Key');
    expect(key).toBeTruthy();
    first.flush({ error: { message: 'falhou' } }, { status: 500, statusText: 'x' });

    component.confirmAdd();
    const retry = backend.expectOne('/api/v1/tickets/p1/children');
    expect(retry.request.headers.get('Idempotency-Key')).toBe(key);
    retry.flush([{ id: 'c3' }]);
    backend.expectOne('/api/v1/tickets/p1/children').flush(OVERVIEW);
  });
});
