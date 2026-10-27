import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';

import { AuthService } from '../../../core/auth/auth.service';
import { CategoryListComponent } from './category-list.component';

const POLICIES = [
  { id: 'p1', name: 'Ouro', is_active: true, targets: [], category_names: [] },
  { id: 'p2', name: 'Prata', is_active: false, targets: [], category_names: [] }
];
const CATEGORY = { id: 'k1', name: 'Rede', default_sector_id: null, form_schema: [], sla_policy_id: 'p2' };

async function mount(permissions: string[]) {
  await TestBed.configureTestingModule({
    imports: [CategoryListComponent],
    providers: [
      provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations(),
      { provide: AuthService, useValue: { hasPermission: (p: string) => permissions.includes(p) } }
    ]
  }).compileComponents();
  const http = TestBed.inject(HttpTestingController);
  const fixture = TestBed.createComponent(CategoryListComponent);
  fixture.componentInstance['snackBar'] = { open: vi.fn() } as unknown as MatSnackBar;
  fixture.detectChanges();
  http.expectOne('/api/v1/tickets/categories').flush([CATEGORY]);
  http.match('/api/v1/organization/sectors').forEach((r) => r.flush([]));
  http.expectOne('/api/v1/sla/policies').flush(POLICIES);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return { fixture, cmp: fixture.componentInstance, http };
}

describe('Categoria de chamado: campo SLA', () => {
  it('shows the SLA of each category in the table', async () => {
    const { fixture } = await mount([]);
    expect(fixture.nativeElement.querySelector('[data-testid="sla-Rede"]').textContent).toContain('Prata (inativa)');
    expect(fixture.componentInstance.getSlaName(null)).toBe('Não se aplica');
  });

  it('lets SLA managers choose the policy and sends it', async () => {
    const { fixture, cmp, http } = await mount(['service_desk.sla.manage']);
    cmp.edit(CATEGORY as never);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="category-sla"]')).toBeTruthy();
    expect(cmp.catForm.value.sla_policy_id).toBe('p2');
    cmp.catForm.patchValue({ sla_policy_id: null });
    cmp.onSubmit();
    const req = http.expectOne((r) => r.method === 'PATCH' && r.url === '/api/v1/tickets/categories/k1');
    expect(req.request.body.sla_policy_id).toBeNull();
    expect('sla_policy_id' in req.request.body).toBe(true);
  });

  it('hides the field and never sends it without the SLA permission', async () => {
    const { fixture, cmp, http } = await mount(['service_desk.categories.manage']);
    cmp.edit(CATEGORY as never);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="category-sla"]')).toBeNull();
    cmp.onSubmit();
    const req = http.expectOne((r) => r.method === 'PATCH' && r.url === '/api/v1/tickets/categories/k1');
    expect('sla_policy_id' in req.request.body).toBe(false);
  });
});
