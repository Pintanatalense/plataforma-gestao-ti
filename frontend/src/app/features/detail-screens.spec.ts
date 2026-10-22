import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

import { InventoryDetailComponent } from './inventory/inventory-detail/inventory-detail.component';
import { TicketDetailComponent } from './service-desk/ticket-detail/ticket-detail.component';
import { StockDetailComponent } from './stock/stock-detail/stock-detail.component';

/**
 * Telas de detalhe dependem de UM objeto. Se a chamada falha, a tela não pode ficar em branco:
 * mostra o motivo e "Tentar novamente".
 */
const CASES: { name: string; component: Type<unknown>; url: string }[] = [
  { name: 'Chamado', component: TicketDetailComponent, url: '/api/v1/tickets/1' },
  { name: 'Item de estoque', component: StockDetailComponent, url: '/api/v1/stock/items/1' },
  { name: 'Auditoria de inventário', component: InventoryDetailComponent, url: '/api/v1/inventory/1' }
];

// ActivatedRoute completo: algumas telas leem params/queryParams como observables
const route = {
  snapshot: { paramMap: convertToParamMap({ id: '1' }), queryParamMap: convertToParamMap({}) },
  paramMap: of(convertToParamMap({ id: '1' })),
  queryParamMap: of(convertToParamMap({})),
  params: of({ id: '1' }),
  queryParams: of({}),
  data: of({})
};

describe.each(CASES)('Tela de detalhe: $name', (c) => {
  let fixture: ComponentFixture<unknown>;
  let backend: HttpTestingController;
  const q = (sel: string) => fixture.nativeElement.querySelector(sel) as HTMLElement | null;
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [c.component],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync(),
        { provide: ActivatedRoute, useValue: route }
      ]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(c.component);
    await settle();
  });

  it('shows a loading state while the object is being fetched', () => {
    expect(q('[data-testid="state-loading"]')).toBeTruthy();
    backend.expectOne(c.url);
  });

  it('on failure shows the error with retry instead of a blank screen', async () => {
    backend.expectOne(c.url).flush({ error: { message: 'Registro não encontrado.' } }, { status: 404, statusText: 'Not Found' });
    await settle();
    expect(q('[data-testid="state-error"]')?.textContent).toContain('Registro não encontrado.');
    expect(q('[data-testid="state-retry"]')).toBeTruthy();
    expect(q('[data-testid="state-loading"]')).toBeNull();
  });

  it('"Tentar novamente" requests the object again', async () => {
    backend.expectOne(c.url).error(new ProgressEvent('error'), { status: 0 });
    await settle();
    (q('[data-testid="state-retry"]') as HTMLButtonElement).click();
    await settle();
    backend.expectOne(c.url); // segunda tentativa
    expect(q('[data-testid="state-error"]')).toBeNull();
  });
});
