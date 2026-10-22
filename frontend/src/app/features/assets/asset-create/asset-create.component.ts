import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AssetCategory, AssetService } from '../../../core/services/asset.service';
import { Employee, OrganizationService, Unit } from '../../../core/services/organization.service';
import { apiErrorMessage } from '../../../core/http/api-error';

interface SpecKey {
  key: string;
  label: string;
}

@Component({
  selector: 'app-asset-create',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule
  ],
  templateUrl: './asset-create.component.html',
  styleUrls: ['./asset-create.component.scss']
})
export class AssetCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private assetService = inject(AssetService);
  private orgService = inject(OrganizationService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  form = this.fb.group({
    tag: ['', Validators.required],
    name: ['', Validators.required],
    category_id: ['', Validators.required],
    status: ['IN_STOCK', Validators.required],
    unit_id: ['', Validators.required],
    employee_id: [null as string | null]
  });

  specsForm: FormGroup = this.fb.group({});
  specKeys: SpecKey[] = [];

  categories: AssetCategory[] = [];
  units: Unit[] = [];
  employees: Employee[] = [];

  ngOnInit(): void {
    this.loadDependencies();

    this.form.get('category_id')?.valueChanges.subscribe((categoryId) => {
      this.onCategoryChange(categoryId);
    });
  }

  loadDependencies(): void {
    this.assetService.getCategories().subscribe({
      next: (cats) => (this.categories = cats),
      error: (err) => console.error('Erro ao carregar categorias:', err)
    });

    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        if (units.length > 0 && !this.form.get('unit_id')?.value) {
          this.form.get('unit_id')?.setValue(units[0].id);
        }
      },
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });

    this.orgService.getEmployees().subscribe({
      next: (emps) => (this.employees = emps),
      error: (err) => console.error('Erro ao carregar colaboradores:', err)
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
      if (typeof val === 'object' && val !== null && 'label' in val) {
        label = (val as any).label || key;
      }
      keys.push({ key, label });
      this.specsForm.addControl(key, this.fb.control(''));
    }

    this.specKeys = keys;
  }

  onSubmit(): void {
    if (this.form.invalid) return;

    const payload = {
      ...this.form.value,
      technical_specs: this.specsForm.value
    };

    this.assetService.createAsset(payload).subscribe({
      next: () => {
        this.snackBar.open('Ativo cadastrado com sucesso!', 'Fechar', { duration: 3000 });
        this.router.navigate(['/assets']);
      },
      error: (err) => {
        console.error('Erro ao cadastrar ativo:', err);
        const errorMsg = apiErrorMessage(err, 'Erro ao cadastrar ativo.');
        this.snackBar.open(errorMsg, 'Fechar', { duration: 5000 });
      }
    });
  }
}
