import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { of } from 'rxjs';
import { AssetCreateComponent } from './assets/asset-create/asset-create.component';
import { StockCreateComponent } from './stock/stock-create/stock-create.component';
import { StockDetailComponent } from './stock/stock-detail/stock-detail.component';

const fail = { error: { message: 'Banco indisponível.' } };
const bad = { status: 403, statusText: 'x' };

async function setup(cmp: Type<unknown>) {
  await TestBed.configureTestingModule({
    imports: [cmp],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      provideNoopAnimations(),
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: 'abc' }) }, paramMap: of(convertToParamMap({ id: 'abc' })) } }
    ]
  }).compileComponents();
  const fixture: ComponentFixture<any> = TestBed.createComponent(cmp);
  const backend = TestBed.inject(HttpTestingController);
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  return { fixture, backend, settle, text: () => fixture.nativeElement.textContent as string };
}

describe.each([
  { name: 'Cadastro de ativo', cmp: AssetCreateComponent, units: '/api/v1/organization/units', cats: '/api/v1/assets/categories' },
  { name: 'Cadastro de estoque', cmp: StockCreateComponent, units: '/api/v1/organization/units', cats: '/api/v1/stock/categories' }
])('$name: falha nas listas de apoio não deixa um formulário "vazio" sem explicação', ({ cmp, units, cats }) => {
  it('mostra o erro com "Tentar novamente", esconde o formulário e recarrega', async () => {
    const { fixture, backend, settle, text } = await setup(cmp);
    fixture.detectChanges();
    backend.match((r) => r.url.endsWith('/employees')).forEach((r) => r.flush([]));
    backend.expectOne((r) => r.url === units).flush(fail, bad);
    backend.expectOne((r) => r.url === cats).flush([]);
    await settle();

    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(text()).toContain('Banco indisponível.');
    expect(fixture.nativeElement.querySelector('form')).toBeNull();

    (fixture.nativeElement.querySelector('[data-testid="state-retry"]') as HTMLButtonElement).click();
    backend.match((r) => r.url.endsWith('/employees')).forEach((r) => r.flush([]));
    backend.expectOne((r) => r.url === units).flush([{ id: 'u1', name: 'Matriz', code: 'M' }]);
    backend.expectOne((r) => r.url === cats).flush([]);
    await settle();

    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeNull();
    expect(fixture.nativeElement.querySelector('form')).toBeTruthy();
  });
});

describe('Detalhe do insumo: movimentações que falham não parecem "sem movimentações"', () => {
  it('mostra o erro e recarrega', async () => {
    const { fixture, backend, settle, text } = await setup(StockDetailComponent);
    fixture.detectChanges();
    backend.match((r) => !r.url.includes('/movements')).forEach((r) => r.flush({ id: 'abc', name: 'Toner', quantity: 1, min_quantity: 1, unit_id: 'u1' }));
    backend.expectOne((r) => r.url.includes('/movements')).flush(fail, bad);
    await settle();

    expect(text()).toContain('Banco indisponível.');
    expect(text()).not.toContain('Nenhuma movimentação');

    (fixture.nativeElement.querySelector('[data-testid="state-retry"]') as HTMLButtonElement).click();
    backend.expectOne((r) => r.url.includes('/movements')).flush([]);
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeNull();
  });
});
