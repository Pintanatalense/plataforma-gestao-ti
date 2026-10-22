import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { StockCategory, StockService } from '../../../core/services/stock.service';
import { OrganizationService, Unit } from '../../../core/services/organization.service';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';

interface SpecKey {
  key: string;
  label: string;
  required: boolean;
}

@Component({
  selector: 'app-stock-create',
  standalone: true,
  imports: [
    CommonModule,
    LoadStateComponent,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule
  ],
  templateUrl: './stock-create.component.html',
  styleUrls: ['./stock-create.component.scss']
})
export class StockCreateComponent implements OnInit {
  private cdr = inject(ChangeDetectorRef);
  private fb = inject(FormBuilder);
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  form = this.fb.group({
    name: ['', Validators.required],
    unit_id: ['', Validators.required],
    category_id: [null as string | null],
    description: [''],
    initial_quantity: [0, [Validators.required, Validators.min(0)]],
    min_quantity: [0, [Validators.required, Validators.min(0)]]
  });

  specsForm: FormGroup = this.fb.group({});
  specKeys: SpecKey[] = [];

  categories: StockCategory[] = [];
  units: Unit[] = [];

  ngOnInit(): void {
    this.loadDependencies();

    this.form.get('category_id')?.valueChanges.subscribe((categoryId) => {
      this.onCategoryChange(categoryId);
    });
  }

  /** Listas de apoio (unidades, categorias...): sem elas o formulário não pode ser preenchido. */
  dependencyError: string | null = null;

  private failDependency(err: unknown, what: string): void {
    this.dependencyError = apiErrorMessage(err, `Não foi possível carregar ${what}.`);
    this.cdr.markForCheck();
  }

  loadDependencies(): void {
    this.dependencyError = null;
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        this.cdr.markForCheck();
        if (units.length > 0 && !this.form.get('unit_id')?.value) {
          this.form.get('unit_id')?.setValue(units[0].id);
        }
      },
      error: (err) => this.failDependency(err, 'as listas de apoio (unidades)')
    });

    this.stockService.getCategories().subscribe({
      next: (cats) => {
        this.categories = cats;
        this.cdr.markForCheck();
      },
      error: (err) => this.failDependency(err, 'as listas de apoio (categorias de estoque)')
    });
  }

  onCategoryChange(categoryId: string | null): void {
    this.specKeys = [];
    this.specsForm = this.fb.group({});

    if (!categoryId) return;
    const cat = this.categories.find((c) => c.id === categoryId);
    if (!cat || !cat.spec_schema) return;

    const schema = cat.spec_schema;
    const keys: SpecKey[] = [];

    for (const [key, val] of Object.entries(schema)) {
      let label = key;
      let required = false;

      if (typeof val === 'object' && val !== null) {
        label = (val as any).label || key;
        required = !!(val as any).required;
      }

      keys.push({ key, label, required });
      this.specsForm.addControl(
        key,
        this.fb.control('', required ? [Validators.required] : [])
      );
    }

    this.specKeys = keys;
  }

  onSubmit(): void {
    if (this.form.invalid || this.specsForm.invalid) return;

    const val = this.form.value;
    const payload = {
      name: val.name!,
      unit_id: val.unit_id!,
      category_id: val.category_id || undefined,
      description: val.description || undefined,
      initial_quantity: Number(val.initial_quantity || 0),
      min_quantity: Number(val.min_quantity || 0),
      technical_specs: this.specsForm.value
    };

    this.stockService.createItem(payload).subscribe({
      next: () => {
        this.snackBar.open('Item de estoque criado com sucesso!', 'Fechar', { duration: 3000 });
        this.router.navigate(['/stock']);
      },
      error: (err) => {
        console.error('Erro ao cadastrar insumo:', err);
        const errorMsg = apiErrorMessage(err, 'Erro ao cadastrar insumo.');
        this.snackBar.open(errorMsg, 'Fechar', { duration: 5000 });
      }
    });
  }
}
