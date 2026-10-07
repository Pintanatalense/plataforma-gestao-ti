import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SectorList } from './sector-list.component';

describe('SectorList', () => {
  let component: SectorList;
  let fixture: ComponentFixture<SectorList>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SectorList],
    }).compileComponents();

    fixture = TestBed.createComponent(SectorList);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
