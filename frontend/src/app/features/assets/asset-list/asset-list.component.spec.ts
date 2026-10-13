import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { AssetListComponent } from './asset-list.component';

describe('AssetListComponent', () => {
  let component: AssetListComponent;
  let fixture: ComponentFixture<AssetListComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AssetListComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AssetListComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should return correct status labels', () => {
    expect(component.getStatusLabel('IN_STOCK')).toBe('Em Estoque');
    expect(component.getStatusLabel('IN_USE')).toBe('Em Uso');
    expect(component.getStatusLabel('MAINTENANCE')).toBe('Manutenção');
    expect(component.getStatusLabel('DECOMMISSIONED')).toBe('Baixado');
  });

  it('should return correct badge classes', () => {
    expect(component.getStatusBadgeClass('IN_STOCK')).toBe('badge-stock');
    expect(component.getStatusBadgeClass('IN_USE')).toBe('badge-use');
    expect(component.getStatusBadgeClass('MAINTENANCE')).toBe('badge-maint');
    expect(component.getStatusBadgeClass('DECOMMISSIONED')).toBe('badge-decom');
  });
});
