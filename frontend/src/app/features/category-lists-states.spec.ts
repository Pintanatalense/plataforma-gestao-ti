import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { MatSnackBar } from '@angular/material/snack-bar';
import { CategoryListComponent as TicketCategoryList } from './service-desk/category-list/category-list.component';
import { AssetCategoryListComponent } from './assets/category-list/category-list.component';
import { StockCategoryListComponent } from './stock/category-list/category-list.component';

const SCREENS: { name: string; cmp: Type<unknown>; url: string }[] = [
  { name: 'Categorias de chamados', cmp: TicketCategoryList, url: '/api/v1/tickets/categories' },
  { name: 'Categorias de ativos', cmp: AssetCategoryListComponent, url: '/api/v1/assets/categories' },
  { name: 'Categorias de estoque', cmp: StockCategoryListComponent, url: '/api/v1/stock/categories' }
];

describe.each(SCREENS)('$name: falha de API não parece lista vazia', ({ cmp, url }) => {
  let fixture: ComponentFixture<any>;
  let backend: HttpTestingController;
  const match = (r: { url: string; method: string }) => r.url === url && r.method === 'GET';
  const settle = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const text = () => fixture.nativeElement.textContent as string;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [cmp],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(cmp);
    fixture.componentInstance.snackBar = { open: vi.fn() } as unknown as MatSnackBar;
    fixture.detectChanges();
    backend.match((r) => r.method === 'GET' && r.url !== url); // setores etc. do ngOnInit: não interessam aqui
  });

  it('mostra o erro do servidor com "Tentar novamente" (nunca "nenhuma categoria")', async () => {
    backend.expectOne(match).flush({ error: { message: 'Sem permissão para listar.' } }, { status: 403, statusText: 'x' });
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeTruthy();
    expect(text()).toContain('Sem permissão para listar.');
    expect(text()).not.toContain('Nenhuma categoria cadastrada.');
    expect(fixture.nativeElement.querySelector('table')).toBeNull();
    expect(text()).not.toContain('0 categorias'); // o contador não diz "zero" quando na verdade não foi lido
  });

  it('"Tentar novamente" refaz a chamada e mostra o estado vazio quando a lista realmente é vazia', async () => {
    backend.expectOne(match).flush({}, { status: 500, statusText: 'x' });
    await settle();
    (fixture.nativeElement.querySelector('[data-testid="state-retry"]') as HTMLButtonElement).click();
    backend.expectOne(match).flush([]);
    await settle();
    expect(fixture.nativeElement.querySelector('[data-testid="state-error"]')).toBeNull();
    expect(text()).toContain('Nenhuma categoria cadastrada.');
  });

  it('recarga que falha depois de carregar mantém a tabela e só avisa', async () => {
    backend.expectOne(match).flush([{ id: '1', name: 'Hardware', description: '', is_active: true, form_schema: [], spec_schema: {} }]);
    await settle();
    fixture.componentInstance.loadData();
    backend.expectOne(match).flush({}, { status: 500, statusText: 'x' });
    await settle();
    expect(fixture.componentInstance.categoriesError).toBeNull();
    expect(fixture.nativeElement.querySelector('table')).toBeTruthy();
    expect(fixture.componentInstance.snackBar.open).toHaveBeenCalled();
  });
});
