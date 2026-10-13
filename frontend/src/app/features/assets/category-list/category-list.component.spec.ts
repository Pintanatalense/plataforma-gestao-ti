import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { AssetCategoryListComponent } from './category-list.component';

describe('AssetCategoryListComponent', () => {
  let component: AssetCategoryListComponent;
  let fixture: ComponentFixture<AssetCategoryListComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AssetCategoryListComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(AssetCategoryListComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize with empty editing state and form invalid when empty', () => {
    expect(component.editingCategory).toBeNull();
    expect(component.catForm.valid).toBe(false);
  });

  it('should apply preset correctly', () => {
    component.applyPreset('computer');
    expect(component.specFields.length).toBe(5);
    expect(component.specFields[0].name).toBe('Processador');
    expect(component.specFields[0].required).toBe(true);
  });

  it('should add and remove spec fields', () => {
    component.addSpecField();
    expect(component.specFields.length).toBe(1);
    component.removeSpecField(0);
    expect(component.specFields.length).toBe(0);
  });
});
