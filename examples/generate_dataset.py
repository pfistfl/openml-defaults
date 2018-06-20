import arff
import argparse
import ConfigSpace
import numpy as np
import openml
import openmlcontrib
import openmldefaults
import os
import pandas as pd
import sklearn
import sklearn.ensemble


def parse_args():
    parser = argparse.ArgumentParser(description='Creates an ARFF file')
    parser.add_argument('--cache_directory', type=str, default=os.path.expanduser('~') + '/experiments/openml_cache',
                        help='directory to store cache')
    parser.add_argument('--output_directory', type=str, default=os.path.expanduser('~') + '/experiments/openml-defaults',
                        help='directory to store output')
    parser.add_argument('--study_id', type=str, default='OpenML100', help='the tag to obtain the tasks from')
    parser.add_argument('--classifier', type=str, default='libsvm_svc', help='openml flow id')
    parser.add_argument('--scoring', type=str, default='predictive_accuracy')
    parser.add_argument('--num_runs', type=int, default=500, help='max runs to obtain from openml')
    parser.add_argument('--resized_grid_size', type=int, default=16)
    return parser.parse_args()


def generate_configurations(config_space, current_index, max_values_per_parameter):
    if current_index >= len(config_space.get_hyperparameters()):
        return [{}]
    else:
        current_hyperparameter = config_space.get_hyperparameter(config_space.get_hyperparameter_by_idx(current_index))
        if isinstance(current_hyperparameter, ConfigSpace.CategoricalHyperparameter):
            current_values = current_hyperparameter.choices
        elif isinstance(current_hyperparameter, ConfigSpace.UniformFloatHyperparameter):
            if current_hyperparameter.log:
                current_values = np.logspace(np.log(current_hyperparameter.lower),
                                             np.log(current_hyperparameter.upper),
                                             num=max_values_per_parameter,
                                             base=np.e)
            else:
                current_values = np.linspace(current_hyperparameter.lower, current_hyperparameter.upper,
                                             num=max_values_per_parameter)
        elif isinstance(current_hyperparameter, ConfigSpace.UniformIntegerHyperparameter):
            possible_values = current_hyperparameter.upper - current_hyperparameter.lower + 1
            if current_hyperparameter.log:
                current_values = np.logspace(np.log(current_hyperparameter.lower),
                                             np.log(current_hyperparameter.upper),
                                             num=min(max_values_per_parameter, possible_values),
                                             base=np.e)
            else:
                current_values = np.linspace(current_hyperparameter.lower, current_hyperparameter.upper,
                                             num=min(max_values_per_parameter, possible_values))
            current_values = [np.round(val) for val in list(current_values)]
        elif isinstance(current_hyperparameter, ConfigSpace.UnParametrizedHyperparameter) or \
                isinstance(current_hyperparameter, ConfigSpace.Constant):
            current_values = [current_hyperparameter.value]
        else:
            raise ValueError('Could not determine hyperparameter type: %s' % current_hyperparameter.name)

        result = []
        recursive_configs = generate_configurations(config_space, current_index+1, max_values_per_parameter)
        for recursive_config in recursive_configs:
            for i in range(len(current_values)):
                current_value = current_values[i]
                cp = dict(recursive_config)
                cp[current_hyperparameter.name] = current_value
                result.append(cp)
        return result


def train_surrogate_on_task(task_id, flow_id, num_runs, config_space, scoring, cache_directory):
    nominal_values_min = 10
    # obtain the data
    setup_data = openmlcontrib.meta.get_task_flow_results_as_dataframe(task_id=task_id,
                                                                       flow_id=flow_id,
                                                                       num_runs=num_runs,
                                                                       configuration_space=config_space,
                                                                       parameter_field='parameter_name',
                                                                       evaluation_measure=scoring,
                                                                       cache_directory=cache_directory)

    # assert that we have ample values for all categorical options
    for hyperparameter in config_space:
        if isinstance(hyperparameter, ConfigSpace.CategoricalHyperparameter):
            for value in hyperparameter.values:
                num_occurances = len(setup_data.loc[setup_data[hyperparameter.name] == value])
                if num_occurances < nominal_values_min:
                    raise ValueError('Nominal hyperparameter %s value %s does not have' % (hyperparameter.name, value) +
                                     ' enough values. Required %d, got: %d' % (nominal_values_min, num_occurances))

    y = setup_data['y'].values
    del setup_data['y']
    print(openmldefaults.utils.get_time(), 'Dimensions of meta-data task %d: %s' % (task_id, str(setup_data.shape)))

    # TODO: HPO
    surrogate = sklearn.pipeline.Pipeline(steps=[
        ('imputer', sklearn.preprocessing.Imputer(strategy='median')),
        ('classifier', sklearn.ensemble.RandomForestRegressor(n_estimators=64))
    ])
    surrogate.fit(pd.get_dummies(setup_data).as_matrix(), y)
    return surrogate, setup_data.columns.values


def run(args):
    study = openml.study.get_study(args.study_id, 'tasks')

    if args.classifier == 'random_forest':
        flow_id = 6969
        config_space = openmldefaults.config_spaces.get_random_forest_default_search_space()
    elif args.classifier == 'adaboost':
        flow_id = 6970
        config_space = openmldefaults.config_spaces.get_adaboost_default_search_space()
    elif args.classifier == 'libsvm_svc':
        flow_id = 7707
        config_space = openmldefaults.config_spaces.get_libsvm_svc_default_search_space()
    else:
        raise ValueError('classifier type not recognized')

    num_params = len(config_space.get_hyperparameter_names())
    configurations = generate_configurations(config_space, 0, args.resized_grid_size)
    df_orig = pd.DataFrame(configurations)

    df_surrogate = df_orig.copy()
    for task_id in study.tasks:
        try:
            estimator, columns = train_surrogate_on_task(task_id, flow_id, args.num_runs,
                                                         config_space, args.scoring, args.cache_directory)
        except ValueError as e:
            print('Error at task %d: %s' % (task_id, e))
            continue
        if not np.array_equal(df_orig.columns.values, columns):
            raise ValueError()
        surrogate_values = estimator.predict(pd.get_dummies(df_orig).as_matrix())
        df_surrogate['%s_task_%d' % (args.scoring, task_id)] = surrogate_values

    if df_surrogate.shape != (len(configurations), num_params+len(study.tasks)):
        raise ValueError()
    os.makedirs(args.output_directory, exist_ok=True)
    arff_object = openmlcontrib.meta.dataframe_to_arff(df_surrogate, 'surrogate_%s' % args.classifier,
                                                       'Generated using OpenML-defaults')
    with open(os.path.join(args.output_directory, 'aurrogate_%s_c%d.arff' % (args.classifier,
                                                                             args.resized_grid_size)), 'w') as fp:
        arff.dump(arff_object, fp)


if __name__ == '__main__':
    run(parse_args())
