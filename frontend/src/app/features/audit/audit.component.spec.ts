import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { AuditComponent } from './audit.component';

const URL = '/api/v1/audit';
const entry = (n: number, extra: object = {}) => ({
  id: `id-${n}`, event_type: 'identity.login_failed', entity_type: 'user', entity_id: 'e', data: { ip: '10.0.0.1', known_account: true },
  user_id: null, user_email: n % 2 ? 'ana@empresa.com' : null, user_name: null, created_at: '2026-10-22T10:00:00Z', ...extra
});

describe('Tela de auditoria', () => {
  let fixture: ComponentFixture<AuditComponent>;
  let component: AuditComponent;
  let backend: HttpTestingController;
  const list = (r: { url: string; method: string }) => r.url === URL && r.method === 'GET';
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const q = (id: string) => fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AuditComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AuditComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    backend.expectOne(`${URL}/event-types`).flush(['identity.login_failed', 'x.desconhecido']);
  });

  it('shows entries with readable names, the user (or "Sistema") and the total from X-Total-Count', async () => {
    backend.expectOne(list).flush([entry(1), entry(2)], { headers: { 'X-Total-Count': '120' } });
    await settle();
    const text = (q('audit-table') as HTMLElement).textContent!;
    expect(text).toContain('Falha de login');
    expect(text).toContain('ana@empresa.com');
    expect(text).toContain('Sistema / não identificado');
    expect(text).toContain('ip: 10.0.0.1');
    expect(q('audit-range')!.textContent).toContain('1–2 de 120');
  });

  it('a failed load is an error with retry, never "nenhum registro"', async () => {
    backend.expectOne(list).flush({ error: { message: 'Sem permissão.' } }, { status: 403, statusText: 'x' });
    await settle();
    expect(q('state-error')).toBeTruthy();
    expect(fixture.nativeElement.textContent).toContain('Sem permissão.');
    expect(fixture.nativeElement.textContent).not.toContain('Nenhum registro');
    (q('state-retry') as HTMLButtonElement).click();
    backend.expectOne(list).flush([], { headers: { 'X-Total-Count': '0' } });
    await settle();
    expect(q('state-empty')).toBeTruthy();
  });

  it('applying filters sends them to the API (dates as full-day UTC instants) and returns to the first page', async () => {
    backend.expectOne(list).flush([entry(1)], { headers: { 'X-Total-Count': '200' } });
    await settle();
    component.filters = { event_type: 'identity.login_failed', category: 'security', user: ' ana ', date_from: '2026-10-01', date_to: '2026-10-02' };
    component.offset = 100;
    component.apply();
    const req = backend.expectOne(list);
    expect(req.request.params.get('event_type')).toBe('identity.login_failed');
    expect(req.request.params.get('user')).toBe('ana');
    expect(req.request.params.get('category')).toBe('security');
    expect(req.request.params.get('offset')).toBe('0');
    expect(new Date(req.request.params.get('date_from')!).getTime()).toBe(new Date('2026-10-01T00:00:00').getTime());
    expect(new Date(req.request.params.get('date_to')!).getTime()).toBe(new Date('2026-10-02T23:59:59.999').getTime());
    req.flush([], { headers: { 'X-Total-Count': '0' } });
  });

  it('paging keeps the APPLIED filters, not what was typed afterwards', async () => {
    backend.expectOne(list).flush([entry(1)], { headers: { 'X-Total-Count': '200' } });
    await settle();
    component.filters.user = 'digitado-e-nao-aplicado';
    component.go(1);
    const req = backend.expectOne(list);
    expect(req.request.params.get('offset')).toBe('50');
    expect(req.request.params.has('user')).toBe(false);
    req.flush([entry(1)], { headers: { 'X-Total-Count': '200' } });
  });

  it('"Limpar" resets every filter and reloads', async () => {
    backend.expectOne(list).flush([], { headers: { 'X-Total-Count': '0' } });
    await settle();
    component.filters = { event_type: 'x', category: 'operational', user: 'y', date_from: '2026-01-01', date_to: '2026-01-02' };
    component.clear();
    const req = backend.expectOne(list);
    expect(req.request.params.keys().sort()).toEqual(['limit', 'offset']);
    req.flush([], { headers: { 'X-Total-Count': '0' } });
    expect(component.filters.user).toBe('');
  });

  it('a late answer to an older search never overwrites the newest one', async () => {
    backend.expectOne(list).flush([], { headers: { 'X-Total-Count': '0' } });
    await settle();
    component.go(1);
    const older = backend.expectOne(list);
    component.go(1);
    const newer = backend.expectOne(list);
    newer.flush([entry(2)], { headers: { 'X-Total-Count': '200' } });
    older.flush([entry(1)], { headers: { 'X-Total-Count': '999' } });
    await settle();
    expect(component.total).toBe(200);
    expect(component.entries[0].id).toBe('id-2');
  });
});
