import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { map, of, switchMap, throwError, timer } from 'rxjs';

import { AssetService } from '../core/services/asset.service';
import { InventoryService } from '../core/services/inventory.service';
import { OrganizationService } from '../core/services/organization.service';
import { StockService } from '../core/services/stock.service';
import { AssetListComponent } from './assets/asset-list/asset-list.component';
import { InventoryListComponent } from './inventory/inventory-list/inventory-list.component';
import { TicketListComponent } from './service-desk/ticket-list/ticket-list.component';
import { TicketService } from './service-desk/ticket.service';
import { StockListComponent } from './stock/stock-list/stock-list.component';

/**
 * Regra: uma falha de comunicação com o backend NUNCA é apresentada como lista vazia.
 * Vale para todas as telas de lista: mostram o erro com "Tentar novamente" e não mostram a tabela nem o "Nenhum … encontrado".
 */
interface ListCase {
  name: string;
  component: Type<unknown>;
  /** token do serviço que carrega a lista e o método chamado */
  service: Type<unknown>;
  method: string;
  extraProviders?: unknown[];
}

/**
 * Respostas ASSÍNCRONAS, como as reais. Os componentes são OnPush (padrão do Angular 22): estado alterado numa
 * resposta HTTP só chega à tela com markForCheck(). Com mocks síncronos o teste passaria mesmo sem ele.
 */
const later = <T>(value: T) => timer(0).pipe(map(() => value));
const laterError = (err: unknown) => timer(0).pipe(switchMap(() => throwError(() => err)));

const units = { provide: OrganizationService, useValue: { getUnits: () => of([]) } };

const CASES: ListCase[] = [
  { name: 'Chamados', component: TicketListComponent, service: TicketService, method: 'listTickets' },
  { name: 'Ativos', component: AssetListComponent, service: AssetService, method: 'getAssets' },
  { name: 'Estoque', component: StockListComponent, service: StockService, method: 'getItems', extraProviders: [units] },
  { name: 'Inventário', component: InventoryListComponent, service: InventoryService, method: 'listAudits', extraProviders: [units] }
];

describe.each(CASES)('Tela de lista: $name', (c) => {
  let fixture: ComponentFixture<unknown>;
  const q = (sel: string) => fixture.nativeElement.querySelector(sel) as HTMLElement | null;

  async function mount(load: ReturnType<typeof vi.fn>) {
    await TestBed.configureTestingModule({
      imports: [c.component],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync(),
        { provide: c.service, useValue: { [c.method]: load } },
        ...(c.extraProviders ?? [])
      ] as never[]
    }).compileComponents();
    fixture = TestBed.createComponent(c.component);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('on failure shows the error and retry, not an empty list', async () => {
    await mount(vi.fn().mockReturnValue(laterError({ status: 500, error: {} })));
    expect(q('[data-testid="state-error"]')).toBeTruthy();
    expect(q('[data-testid="state-retry"]')).toBeTruthy();
    expect(q('table')).toBeNull();
    expect(fixture.nativeElement.textContent).not.toMatch(/Nenhum|Cadastre o primeiro/i);
  });

  it('"Tentar novamente" loads again and then shows the screen', async () => {
    const load = vi
      .fn()
      .mockReturnValueOnce(laterError({ status: 0 }))
      .mockReturnValue(later([]));
    await mount(load);
    expect(q('[data-testid="state-error"]')).toBeTruthy();

    (q('[data-testid="state-retry"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(load).toHaveBeenCalledTimes(2);
    expect(q('[data-testid="state-error"]')).toBeNull();
    expect(q('table')).toBeTruthy();
  });

  it('when the call succeeds with no items, shows the screen (with its own empty message), not the error', async () => {
    await mount(vi.fn().mockReturnValue(later([])));
    expect(q('[data-testid="state-error"]')).toBeNull();
    expect(q('table')).toBeTruthy();
  });
});
